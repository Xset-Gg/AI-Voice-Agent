"""LLM-callable tools. Each one is a thin proxy to the backend, which validates arguments,
checks the business's allowed actions, scopes changes to the caller, and logs everything."""

import json
from typing import TYPE_CHECKING

from livekit.agents import RunContext, StopResponse, function_tool

if TYPE_CHECKING:
    from voice_agent.worker import CallState


def _out(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def build_tools(state: "CallState") -> list:
    b = state.backend
    enabled = set(state.data["tools"])
    tools = []

    @function_tool
    async def search_knowledge_base(context: RunContext, query: str) -> str:
        """Search the business's knowledge base (uploaded documents and FAQs) for facts about services,
        prices, policies, service area or anything else about the business. Use it before answering any
        business question that your instructions don't already cover.

        Args:
            query: A short, specific search query, e.g. "water heater installation price".
        """
        res = await b.tool("search_knowledge_base", {"query": query})
        if not res.get("ok", False):
            return _out({"found": False, "error": res.get("error"), "instruction": "Tell the caller you can't look that up right now."})
        if not res.get("found"):
            hint = await state.failed_turn("knowledge_not_found")
            return (res.get("context") or "NO_RELEVANT_INFORMATION_FOUND") + (f"\n{hint}" if hint else "")
        return res["context"]

    @function_tool
    async def check_availability(context: RunContext, date: str, service: str | None = None, technician_id: str | None = None) -> str:
        """Find open appointment times on a given day.

        Args:
            date: The day to check, formatted YYYY-MM-DD. Resolve words like "tomorrow" using the current date.
            service: What the caller needs done, e.g. "water heater repair". Used to pick a qualified technician.
            technician_id: Only if the caller asked for a specific technician from earlier results.
        """
        args = {"date": date}
        if service:
            args["service"] = service
        if technician_id:
            args["technician_id"] = technician_id
        return _out(await b.tool("check_availability", args))

    @function_tool
    async def book_appointment(
        context: RunContext, technician_id: str, start_time: str, service: str, customer_name: str, notes: str = ""
    ) -> str:
        """Book an appointment for the caller. Only call after the caller has agreed to a specific time.

        Args:
            technician_id: technician_id copied exactly from check_availability results.
            start_time: start_time copied exactly from check_availability results (ISO 8601 with offset).
            service: The service being booked.
            customer_name: The caller's name.
            notes: Short details about the problem, address or access instructions.
        """
        return _out(await b.tool("book_appointment", {
            "technician_id": technician_id, "start_time": start_time, "service": service,
            "customer_name": customer_name, "notes": notes,
        }))

    @function_tool
    async def find_my_appointments(context: RunContext) -> str:
        """List the caller's upcoming appointments (matched by their phone number)."""
        return _out(await b.tool("find_my_appointments", {}))

    @function_tool
    async def reschedule_appointment(context: RunContext, appointment_id: str, new_start_time: str) -> str:
        """Move one of the caller's appointments to a new time the caller agreed to.

        Args:
            appointment_id: appointment_id from find_my_appointments.
            new_start_time: start_time copied from check_availability results.
        """
        return _out(await b.tool("reschedule_appointment", {"appointment_id": appointment_id, "new_start_time": new_start_time}))

    @function_tool
    async def cancel_appointment(context: RunContext, appointment_id: str) -> str:
        """Cancel one of the caller's appointments after they explicitly confirm the cancellation.

        Args:
            appointment_id: appointment_id from find_my_appointments.
        """
        return _out(await b.tool("cancel_appointment", {"appointment_id": appointment_id}))

    @function_tool
    async def transfer_to_human(context: RunContext, reason: str) -> str:
        """Transfer the caller to a human team member. Tell the caller you're connecting them first.

        Args:
            reason: One of caller_request, low_confidence, repeated_failure, sensitive_topic, tool_error, emergency.
        """
        await context.wait_for_playout()
        return await state.transfer(reason)

    @function_tool
    async def end_call(context: RunContext, reason: str = "caller_done") -> None:
        """End the call. Only after the caller says they need nothing else and you have said goodbye.

        Args:
            reason: Why the call is ending, e.g. caller_done.
        """
        await context.wait_for_playout()
        await b.tool("end_call", {"reason": reason})
        await state.hangup("agent_ended")
        raise StopResponse()

    for t in (search_knowledge_base, check_availability, book_appointment, find_my_appointments,
              reschedule_appointment, cancel_appointment, transfer_to_human, end_call):
        if t.info.name in enabled:
            tools.append(t)
    return tools
