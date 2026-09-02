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
class Constitution:
    creator: str
    title: str
    rules: str
    active: bool
    rules_hash: str


@allow_storage
@dataclass
class Proposal:
    constitution_id: u256
    proposer: str

    title: str
    description: str
    amount: u256
    evidence: str

    result: str
    risk: u256
    confidence: u256

    decision_hash: str


class IntelligentDAO(gl.Contract):

    constitutions: DynArray[Constitution]
    proposals: DynArray[Proposal]

    def __init__(self):
        pass

    # ================================================================
    # CREATE CONSTITUTION
    # ================================================================

    @gl.public.write
    def create_constitution(
        self,
        title: str,
        rules: str
    ) -> int:

        title = title.strip()
        rules = rules.strip()

        require(len(title) > 0, "title is empty")
        require(len(rules) > 0, "rules are empty")
        require(len(rules) <= 10000, "rules too long")

        rules_hash = hashlib.sha256(
            canonical({
                "title": title,
                "rules": rules
            }).encode()
        ).hexdigest()

        constitution_id = len(self.constitutions)

        self.constitutions.append(
            Constitution(
                creator=str(gl.message.sender_address),
                title=title,
                rules=rules,
                active=True,
                rules_hash=rules_hash
            )
        )

        return constitution_id

    # ================================================================
    # CREATE PROPOSAL
    # ================================================================

    @gl.public.write
    def create_proposal(
        self,
        constitution_id: int,
        title: str,
        description: str,
        amount: int,
        evidence: str
    ) -> int:

        require(
            0 <= constitution_id < len(self.constitutions),
            "constitution does not exist"
        )

        constitution = self.constitutions[constitution_id]

        require(
            constitution.active,
            "constitution inactive"
        )

        require(len(title.strip()) > 0, "title empty")
        require(len(description.strip()) > 0, "description empty")
        require(amount >= 0, "invalid amount")

        proposal_id = len(self.proposals)

        self.proposals.append(
            Proposal(
                constitution_id=u256(constitution_id),
                proposer=str(gl.message.sender_address),

                title=title.strip(),
                description=description.strip(),
                amount=u256(amount),
                evidence=evidence.strip(),

                result="PENDING",
                risk=u256(0),
                confidence=u256(0),

                decision_hash=""
            )
        )

        return proposal_id

    # ================================================================
    # JUDGE PROPOSAL
    # ================================================================

    @gl.public.write
    def judge_proposal(
        self,
        proposal_id: int
    ) -> str:

        require(
            0 <= proposal_id < len(self.proposals),
            "proposal does not exist"
        )

        proposal = self.proposals[proposal_id]

        require(
            proposal.result == "PENDING",
            "proposal already judged"
        )

        constitution = self.constitutions[
            int(proposal.constitution_id)
        ]

        rules = constitution.rules

        def leader_fn():

            prompt = f"""
You are an intelligent DAO governance judge.

You must evaluate a DAO proposal against the DAO constitution.

CONSTITUTION:
{rules}

PROPOSAL TITLE:
{proposal.title}

PROPOSAL DESCRIPTION:
{proposal.description}

REQUESTED AMOUNT:
{int(proposal.amount)}

EVIDENCE:
{proposal.evidence}

Rules:

1. Follow the constitution exactly.
2. Never invent missing evidence.
3. Identify every violated rule.
4. Consider financial and security risk.
5. If clearly compliant, APPROVE.
6. If clearly violates mandatory rules, REJECT.
7. If information is missing or ambiguous, REVIEW.
8. High financial risk should reduce confidence.
9. Explain the decision briefly.

Return ONLY JSON:

{{
    "result": "APPROVE | REJECT | REVIEW",
    "risk": 0,
    "confidence": 0,
    "violations": [],
    "reason": "short explanation"
}}

risk and confidence must be integers from 0 to 1000.
"""

            result = gl.nondet.exec_prompt(
                prompt,
                response_format="json"
            )

            require(
                isinstance(result, dict),
                "invalid DAO response"
            )

            result_name = str(
                result.get("result", "")
            ).upper()

            require(
                result_name in (
                    "APPROVE",
                    "REJECT",
                    "REVIEW"
                ),
                "invalid result"
            )

            risk = int(result.get("risk", -1))
            confidence = int(
                result.get("confidence", -1)
            )

            require(0 <= risk <= 1000, "invalid risk")
            require(
                0 <= confidence <= 1000,
                "invalid confidence"
            )

            violations = result.get(
                "violations",
                []
            )

            require(
                isinstance(violations, list),
                "invalid violations"
            )

            reason = str(
                result.get("reason", "")
            ).strip()

            require(
                len(reason) > 0,
                "missing reason"
            )

            return {
                "result": result_name,
                "risk": risk,
                "confidence": confidence,
                "violations": violations,
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

            if own["result"] != leader["result"]:
                return False

            if abs(
                int(own["risk"])
                -
                int(leader["risk"])
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

        decision_hash = hashlib.sha256(
            canonical({
                "proposal_id": proposal_id,
                "result": result["result"],
                "risk": result["risk"],
                "confidence": result["confidence"]
            }).encode()
        ).hexdigest()

        self.proposals[proposal_id] = Proposal(
            constitution_id=proposal.constitution_id,
            proposer=proposal.proposer,

            title=proposal.title,
            description=proposal.description,
            amount=proposal.amount,
            evidence=proposal.evidence,

            result=result["result"],
            risk=u256(result["risk"]),
            confidence=u256(result["confidence"]),

            decision_hash=decision_hash
        )

        return result["result"]

    # ================================================================
    # READ PROPOSAL
    # ================================================================

    @gl.public.view
    def get_proposal(
        self,
        proposal_id: int
    ) -> str:

        require(
            0 <= proposal_id < len(self.proposals),
            "proposal does not exist"
        )

        p = self.proposals[proposal_id]

        return canonical({
            "proposal_id": proposal_id,
            "constitution_id": int(p.constitution_id),
            "proposer": p.proposer,
            "title": p.title,
            "description": p.description,
            "amount": int(p.amount),
            "evidence": p.evidence,
            "result": p.result,
            "risk": int(p.risk),
            "confidence": int(p.confidence),
            "decision_hash": p.decision_hash
        })

    @gl.public.view
    def proposal_count(self) -> int:
        return len(self.proposals)

    @gl.public.view
    def constitution_count(self) -> int:
        return len(self.constitutions)
