"""Provider response schema. Application-level evidence checks are separate."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Role = Literal['Backend', 'Frontend', 'Fullstack', 'Mobile', 'Data Analyst', 'Data Engineer',
               'Data Scientist', 'AI/ML Engineer', 'DevOps/SRE', 'Cloud', 'Cybersecurity',
               'QA/Testing', 'Business Analyst', 'other_it_role', 'non_it', 'unknown']
Family = Literal['Software Engineering', 'Data & AI', 'Infrastructure & Security', 'QA & Business']


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    target: Literal['primary_role', 'seniority']
    field: Literal['title', 'description', 'requirements']
    quote: str = Field(min_length=1, max_length=500)


class Proposal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    jd_id: str = Field(min_length=1, max_length=128)
    primary_role: Role
    role_family: Family | None
    seniority: Literal['intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'unknown']
    evidence: list[Evidence] = Field(max_length=8)
    review_required: bool
    review_reasons: list[str] = Field(max_length=8)
