# {
#   "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6"
# }

from genlayer import *
import json
import hashlib
from dataclasses import dataclass


try:
    _Error = gl.vm.UserError
except Exception:
    _Error = Exception


def require(condition: bool, message: str) -> None:
    if not condition:
        raise _Error(message)


def canonical(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":")
    )


@allow_storage
@dataclass
class Project:
    submitter: str

    name: str
    website: str
    documentation: str

    status: str
    risk_score: u256
    confidence: u256

    report_hash: str


class IntelligentRiskOracle(gl.Contract):

    projects: DynArray[Project]

    def __init__(self):
        pass

    # ================================================================
    # REGISTER PROJECT
    # ================================================================

    @gl.public.write
    def register_project(
        self,
        name: str,
        website: str,
        documentation: str
    ) -> int:

        name = name.strip()
        website = website.strip()
        documentation = documentation.strip()

        require(len(name) > 0, "name empty")
        require(len(website) > 0, "website empty")
        require(len(documentation) > 0, "documentation empty")

        project_id = len(self.projects)

        self.projects.append(
            Project(
                submitter=str(gl.message.sender_address),

                name=name,
                website=website,
                documentation=documentation,

                status="PENDING",
                risk_score=u256(0),
                confidence=u256(0),

                report_hash=""
            )
        )

        return project_id

    # ================================================================
    # ANALYZE PROJECT
    # ================================================================

    @gl.public.write
    def analyze_project(
        self,
        project_id: int
    ) -> str:

        require(
            0 <= project_id < len(self.projects),
            "project does not exist"
        )

        project = self.projects[project_id]

        require(
            project.status == "PENDING",
            "project already analyzed"
        )

        def leader_fn():

            website_response = gl.nondet.web.get(
                project.website
            )

            docs_response = gl.nondet.web.get(
                project.documentation
            )

            website = website_response.body.decode(
                "utf-8"
            )

            docs = docs_response.body.decode(
                "utf-8"
            )

            prompt = f"""
You are a blockchain project risk analysis agent.

Analyze the project using ONLY the supplied webpages.

PROJECT:
{project.name}

WEBSITE:
{website}

DOCUMENTATION:
{docs}

Analyze these categories:

1. Team transparency
2. Documentation quality
3. Token/economic transparency
4. Security information
5. Contract information
6. Contradictions between website and documentation
7. Missing important information
8. Potential warning signs

IMPORTANT:

You must NOT claim that a project is a scam merely because
information is missing.

Missing information should increase uncertainty rather
than automatically proving malicious behavior.

Return ONLY JSON:

{{
    "status":
        "LOW_RISK | MEDIUM_RISK | HIGH_RISK | INSUFFICIENT_DATA",

    "risk_score": 0,

    "confidence": 0,

    "signals": [],

    "reason": "short explanation"
}}

Risk score:
0 = very low risk
1000 = extremely high risk

Confidence:
0 = no confidence
1000 = very strong evidence

If there is not enough information,
use INSUFFICIENT_DATA.

Do not invent facts.
"""

            result = gl.nondet.exec_prompt(
                prompt,
                response_format="json"
            )

            require(
                isinstance(result, dict),
                "invalid analysis"
            )

            status = str(
                result.get("status", "")
            ).upper()

            require(
                status in (
                    "LOW_RISK",
                    "MEDIUM_RISK",
                    "HIGH_RISK",
                    "INSUFFICIENT_DATA"
                ),
                "invalid risk status"
            )

            risk_score = int(
                result.get("risk_score", -1)
            )

            confidence = int(
                result.get("confidence", -1)
            )

            require(
                0 <= risk_score <= 1000,
                "invalid risk score"
            )

            require(
                0 <= confidence <= 1000,
                "invalid confidence"
            )

            signals = result.get(
                "signals",
                []
            )

            require(
                isinstance(signals, list),
                "invalid signals"
            )

            reason = str(
                result.get("reason", "")
            ).strip()

            require(
                len(reason) > 0,
                "missing reason"
            )

            return {
                "status": status,
                "risk_score": risk_score,
                "confidence": confidence,
                "signals": signals,
                "reason": reason
            }

        def validator_fn(leader_result):

            if not isinstance(
                leader_result,
                gl.vm.Return
            ):
                return False

            leader = leader_result.calldata

            if not isinstance(leader, dict):
                return False

            own = leader_fn()

            if not isinstance(own, dict):
                return False

            if own["status"] != leader["status"]:
                return False

            if abs(
                int(own["risk_score"])
                -
                int(leader["risk_score"])
            ) > 200:
                return False

            if abs(
                int(own["confidence"])
                -
                int(leader["confidence"])
            ) > 250:
                return False

            return True

        result = gl.vm.run_nondet_unsafe(
            leader_fn,
            validator_fn
        )

        require(
            isinstance(result, dict),
            "invalid consensus"
        )

        report_hash = hashlib.sha256(
            canonical({
                "project_id": project_id,
                "status": result["status"],
                "risk_score": result["risk_score"],
                "confidence": result["confidence"]
            }).encode()
        ).hexdigest()

        self.projects[project_id] = Project(
            submitter=project.submitter,

            name=project.name,
            website=project.website,
            documentation=project.documentation,

            status=result["status"],
            risk_score=u256(
                result["risk_score"]
            ),
            confidence=u256(
                result["confidence"]
            ),

            report_hash=report_hash
        )

        return result["status"]

    # ================================================================
    # GET PROJECT
    # ================================================================

    @gl.public.view
    def get_project(
        self,
        project_id: int
    ) -> str:

        require(
            0 <= project_id < len(self.projects),
            "project does not exist"
        )

        p = self.projects[project_id]

        return canonical({
            "project_id": project_id,
            "submitter": p.submitter,
            "name": p.name,
            "website": p.website,
            "documentation": p.documentation,
            "status": p.status,
            "risk_score": int(p.risk_score),
            "confidence": int(p.confidence),
            "report_hash": p.report_hash
        })

    @gl.public.view
    def project_count(self) -> int:
        return len(self.projects)
