import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import DB, Admin, Viewer, client_ip
from app.core.errors import AppError, NotFound
from app.models import AgentConfig, Organization
from app.schemas.agents import AgentCreate, AgentOut, AgentUpdate
from app.services import audit
from app.services.prompt import build_system_prompt, greeting_for
from app.services.tools.registry import TOOL_SPECS, enabled_tools

router = APIRouter(prefix="/agents", tags=["agents"])


async def _get(db, org_id: uuid.UUID, agent_id: uuid.UUID) -> AgentConfig:
    agent = await db.get(AgentConfig, agent_id)
    if agent is None or agent.org_id != org_id:
        raise NotFound("Agent")
    return agent


def _check_transfer(agent: AgentConfig) -> None:
    if agent.transfer_enabled and not agent.transfer_number:
        raise AppError("A transfer number is required when transfers are enabled", code="transfer_number_required")
    if agent.min_endpointing_delay >= agent.max_endpointing_delay:
        raise AppError("min_endpointing_delay must be less than max_endpointing_delay", code="invalid_timing")


@router.get("", response_model=list[AgentOut])
async def list_agents(principal: Viewer, db: DB):
    return (await db.execute(select(AgentConfig).where(AgentConfig.org_id == principal.org_id).order_by(AgentConfig.created_at))).scalars().all()


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(request: Request, body: AgentCreate, principal: Admin, db: DB):
    data = body.model_dump(exclude_none=True)
    agent = AgentConfig(org_id=principal.org_id, **data)
    _check_transfer(agent)
    db.add(agent)
    await db.flush()
    await audit.record(db, action="agent.created", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="agent", resource_id=agent.id, ip_address=client_ip(request))
    await db.commit()
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, principal: Viewer, db: DB):
    return await _get(db, principal.org_id, agent_id)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(request: Request, agent_id: uuid.UUID, body: AgentUpdate, principal: Admin, db: DB):
    agent = await _get(db, principal.org_id, agent_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is None and k not in ("transfer_number",):
            continue
        setattr(agent, k, v)
    _check_transfer(agent)
    await audit.record(db, action="agent.updated", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="agent", resource_id=agent.id, data={"fields": sorted(changes)}, ip_address=client_ip(request))
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(request: Request, agent_id: uuid.UUID, principal: Admin, db: DB):
    agent = await _get(db, principal.org_id, agent_id)
    await db.delete(agent)
    await audit.record(db, action="agent.deleted", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="agent", resource_id=agent_id, ip_address=client_ip(request))
    await db.commit()


@router.get("/{agent_id}/prompt-preview")
async def prompt_preview(agent_id: uuid.UUID, principal: Viewer, db: DB):
    """Exactly what the voice agent will be instructed with (minus per-caller details)."""
    agent = await _get(db, principal.org_id, agent_id)
    org = await db.get(Organization, principal.org_id)
    return {
        "greeting": greeting_for(agent, org.name),
        "system_prompt": build_system_prompt(agent, org.name, caller_name=None),
        "tools": enabled_tools(agent.allowed_actions, agent.transfer_enabled),
    }


tools_router = APIRouter(prefix="/tools", tags=["tools"])


@tools_router.get("")
async def list_tools(principal: Viewer):
    return [
        {"name": t.name, "title": t.title, "description": t.description, "category": t.category,
         "always_on": t.always_on, "mutates": t.mutates, "requires": list(t.requires)}
        for t in TOOL_SPECS.values()
    ]
