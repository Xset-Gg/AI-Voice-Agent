"""Tool catalogue. The voice worker exposes these to the LLM, but every execution goes through
the backend, which re-checks permissions and validates arguments — the LLM is never trusted."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    category: str
    # Always available regardless of allowed_actions (safe, read-only or call-control)
    always_on: bool = False
    requires: tuple[str, ...] = field(default_factory=tuple)
    mutates: bool = False


TOOL_SPECS: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec(
            "search_knowledge_base", "Knowledge base search",
            "Look up facts about the business (services, prices, policies, hours) in uploaded documents and FAQs.",
            "knowledge", always_on=True,
        ),
        ToolSpec(
            "check_availability", "Check availability",
            "List open appointment times for technicians on a given day.", "scheduling", requires=("technicians",),
        ),
        ToolSpec(
            "book_appointment", "Book appointment",
            "Create an appointment for the caller and add it to the technician's calendar.",
            "scheduling", requires=("technicians",), mutates=True,
        ),
        ToolSpec(
            "find_my_appointments", "Find caller's appointments",
            "Find upcoming appointments booked under the caller's phone number.", "scheduling",
        ),
        ToolSpec(
            "reschedule_appointment", "Reschedule appointment",
            "Move one of the caller's appointments to a new time.", "scheduling", mutates=True,
        ),
        ToolSpec(
            "cancel_appointment", "Cancel appointment",
            "Cancel one of the caller's appointments.", "scheduling", mutates=True,
        ),
        ToolSpec(
            "transfer_to_human", "Transfer to human",
            "Hand the call to a staff member at the configured transfer number.", "call_control",
            requires=("transfer_number",),
        ),
        ToolSpec("end_call", "End call", "Politely end the call once the caller is done.", "call_control", always_on=True),
    ]
}

DEFAULT_ALLOWED_ACTIONS = [
    "check_availability", "book_appointment", "find_my_appointments",
    "reschedule_appointment", "cancel_appointment", "transfer_to_human",
]


def enabled_tools(allowed_actions: list[str], transfer_enabled: bool) -> list[str]:
    names = []
    for name, spec in TOOL_SPECS.items():
        if spec.always_on or name in allowed_actions:
            if name == "transfer_to_human" and not transfer_enabled:
                continue
            names.append(name)
    return names
