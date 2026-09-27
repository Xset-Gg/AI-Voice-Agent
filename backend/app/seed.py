"""Seed a demo business so the platform is usable immediately.

    python -m app.seed

Creates: an organization, an owner login, a configured voice agent, two technicians on the
internal calendar and a set of FAQ knowledge entries (indexed if an embedding key is set).
It does NOT create calls, transcripts or appointments â€” those only come from real activity.
Set SEED_PHONE_NUMBER to a Twilio number you own to attach it to the agent.
"""

import asyncio
import hashlib
import os
import secrets

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import AgentConfig, KnowledgeDocument, Organization, PhoneNumber, Role, Technician, User
from app.services.rag.ingest import ingest_document
from app.services.tools.registry import DEFAULT_ALLOWED_ACTIONS

TZ = os.getenv("SEED_TIMEZONE", "America/New_York")

BUSINESS_INFO = """Bright Home Services is a residential plumbing and HVAC company.
Service area: the greater Springfield metro area.
Services: drain cleaning, leak repair, water heater installation and repair, furnace repair, AC tune-ups and repair.
Standard service call fee: $89, waived if the customer proceeds with the repair.
Payment: we take payment on site after the job; we never take card details over the phone."""

FAQS = [
    ("What are your hours?", "We're open Monday to Friday from 8 AM to 6 PM and Saturday from 9 AM to 1 PM. We're closed on Sundays."),
    ("Do you offer emergency service?", "For burst pipes, gas smells or flooding, customers should first shut off the water or gas and, for gas smells, leave the home and call the gas utility. Our team can then be reached through a transfer to our on-call line."),
    ("How much is a service call?", "The standard service call fee is $89. It is waived if you go ahead with the repair we quote."),
    ("How long does a water heater installation take?", "A standard tank water heater replacement usually takes 2 to 3 hours. Tankless conversions take most of a day."),
    ("Do you give free estimates?", "We give free estimates for water heater replacements and new AC or furnace installations. Diagnostic visits for repairs carry the standard $89 service call fee."),
    ("What is your cancellation policy?", "Please cancel or reschedule at least 24 hours before your appointment. There's no fee for cancelling with notice."),
    ("Are your technicians licensed?", "Yes. All of our technicians are licensed and insured, and they carry company ID."),
    ("Do you offer maintenance plans?", "Yes, our Comfort Club plan is $15 a month and includes two tune-ups a year, priority scheduling and 10 percent off repairs."),
]

WEEKDAY_HOURS = {
    "mon": [["08:00", "18:00"]], "tue": [["08:00", "18:00"]], "wed": [["08:00", "18:00"]],
    "thu": [["08:00", "18:00"]], "fri": [["08:00", "18:00"]], "sat": [["09:00", "13:00"]], "sun": [],
}


async def main() -> None:
    settings = get_settings()
    email = os.getenv("SEED_ADMIN_EMAIL", "owner@brighthome-demo.com").lower()
    password = os.getenv("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(12) + "1a"

    async with SessionLocal() as db:
        if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
            print(f"Seed user {email} already exists â€” nothing to do.")
            return

        org = Organization(name="Bright Home Services", slug=f"bright-home-{secrets.token_hex(2)}", timezone=TZ)
        db.add(org)
        await db.flush()
        db.add(User(org_id=org.id, email=email, full_name="Demo Owner", password_hash=hash_password(password), role=Role.owner))

        agent = AgentConfig(
            org_id=org.id, name="Ava", timezone=TZ,
            greeting="Thanks for calling Bright Home Services, this is Ava. How can I help you today?",
            after_hours_greeting="Thanks for calling Bright Home Services, this is Ava. We're closed right now, but I can answer questions or book you an appointment.",
            personality="Friendly, upbeat and efficient. Sounds like a helpful local office coordinator, not a robot.",
            system_instructions="If a caller mentions a gas smell, tell them to leave the home and call the gas utility's emergency line first.",
            business_info=BUSINESS_INFO, working_hours=WEEKDAY_HOURS,
            allowed_actions=list(DEFAULT_ALLOWED_ACTIONS),
            transfer_enabled=bool(os.getenv("SEED_TRANSFER_NUMBER")), transfer_number=os.getenv("SEED_TRANSFER_NUMBER") or None,
        )
        db.add(agent)
        db.add_all([
            Technician(org_id=org.id, name="Marcus Lee", skills=["plumbing", "drain cleaning", "water heater", "leak repair"],
                       timezone=TZ, working_hours=WEEKDAY_HOURS),
            Technician(org_id=org.id, name="Priya Shah", skills=["hvac", "furnace", "ac", "air conditioning", "tune-up"],
                       timezone=TZ, working_hours=WEEKDAY_HOURS),
        ])
        await db.flush()

        if phone := os.getenv("SEED_PHONE_NUMBER"):
            db.add(PhoneNumber(org_id=org.id, agent_id=agent.id, e164=phone, friendly_name="Main line"))

        docs = []
        for q, a in FAQS:
            text = f"Q: {q}\nA: {a}"
            doc = KnowledgeDocument(org_id=org.id, title=q, source_type="faq", body=text,
                                    size_bytes=len(text), sha256=hashlib.sha256(text.encode()).hexdigest())
            db.add(doc)
            docs.append(doc)
        await db.commit()

        can_embed = settings.openai_api_key if settings.embedding_provider == "openai" else settings.gemini_api_key
        if can_embed:
            for doc in docs:
                await ingest_document(db, doc.id)
            print(f"Indexed {len(docs)} FAQ entries.")
        else:
            print("No embedding API key configured: FAQs saved as 'pending'. Use 'Reprocess' in the dashboard once keys are set.")

    print("\nDemo organization created.")
    print(f"  Login:    {email}")
    print(f"  Password: {password}")


if __name__ == "__main__":
    asyncio.run(main())
