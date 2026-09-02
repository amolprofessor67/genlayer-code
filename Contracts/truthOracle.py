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
class Claim:
    creator: str
    statement: str
    source_a: str
    source_b: str

    status: str
    confidence: u256

    explanation_hash: str
    claim_hash: str


class IntelligentTruthOracle(gl.Contract):

    claims: DynArray[Claim]

    def __init__(self):
        pass

    # ================================================================
    # CREATE CLAIM
    # ================================================================

    @gl.public.write
    def create_claim(
        self,
        statement: str,
        source_a: str,
        source_b: str
    ) -> int:

        statement = statement.strip()
        source_a = source_a.strip()
        source_b = source_b.strip()

        require(len(statement) > 0, "statement is empty")
        require(len(source_a) > 0, "source A is empty")
        require(len(source_b) > 0, "source B is empty")

        require(
            source_a != source_b,
            "sources must be different"
        )

        claim_id = len(self.claims)

        self.claims.append(
            Claim(
                creator=str(gl.message.sender_address),

                statement=statement,
                source_a=source_a,
                source_b=source_b,

                status="PENDING",
                confidence=u256(0),

                explanation_hash="",
                claim_hash=""
            )
        )

        return claim_id

    # ================================================================
    # VERIFY CLAIM
    # ================================================================

    @gl.public.write
    def verify_claim(self, claim_id: int) -> str:

        require(
            0 <= claim_id < len(self.claims),
            "claim does not exist"
        )

        claim = self.claims[claim_id]

        require(
            claim.status == "PENDING",
            "claim already evaluated"
        )

        statement = claim.statement
        source_a = claim.source_a
        source_b = claim.source_b

        # ------------------------------------------------------------
        # LEADER
        # ------------------------------------------------------------

        def leader_fn():

            page_a = gl.nondet.web.get(source_a)
            page_b = gl.nondet.web.get(source_b)

            text_a = page_a.body.decode("utf-8")
            text_b = page_b.body.decode("utf-8")

            prompt = f"""
You are an independent fact verification agent.

Your job is to determine whether a CLAIM is supported
by two external sources.

CLAIM:
{statement}

SOURCE A:
{text_a}

SOURCE B:
{text_b}

Rules:

1. Only use information present in the supplied webpages.
2. Do not use your previous knowledge.
3. Do not invent facts.
4. Evidence must directly relate to the claim.
5. If both sources support the claim, it can be TRUE.
6. If both sources contradict the claim, it can be FALSE.
7. If the sources conflict, are insufficient, or ambiguous,
   choose UNCERTAIN.
8. Confidence must reflect the quality and agreement of evidence.

Return ONLY JSON:

{{
    "status": "TRUE | FALSE | UNCERTAIN",
    "confidence": 0,
    "source_a_support": "SUPPORTS | CONTRADICTS | UNKNOWN",
    "source_b_support": "SUPPORTS | CONTRADICTS | UNKNOWN",
    "reason": "short explanation"
}}

Confidence must be an integer from 0 to 1000.
"""

            result = gl.nondet.exec_prompt(
                prompt,
                response_format="json"
            )

            require(
                isinstance(result, dict),
                "invalid oracle response"
            )

            status = str(
                result.get("status", "")
            ).upper()

            require(
                status in (
                    "TRUE",
                    "FALSE",
                    "UNCERTAIN"
                ),
                "invalid status"
            )

            confidence = int(
                result.get("confidence", -1)
            )

            require(
                0 <= confidence <= 1000,
                "invalid confidence"
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
                "confidence": confidence,
                "source_a_support":
                    result.get("source_a_support", "UNKNOWN"),
                "source_b_support":
                    result.get("source_b_support", "UNKNOWN"),
                "reason": reason
            }

        # ------------------------------------------------------------
        # VALIDATOR
        # ------------------------------------------------------------

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

            # Main decision must agree.
            if own["status"] != leader["status"]:
                return False

            # Large confidence disagreement is suspicious.
            if abs(
                int(own["confidence"])
                -
                int(leader["confidence"])
            ) > 200:
                return False

            return True

        # ------------------------------------------------------------
        # CONSENSUS
        # ------------------------------------------------------------

        result = gl.vm.run_nondet_unsafe(
            leader_fn,
            validator_fn
        )

        require(
            isinstance(result, dict),
            "invalid consensus result"
        )

        status = result["status"]
        confidence = int(result["confidence"])
        reason = str(result["reason"])

        # ------------------------------------------------------------
        # HASHES
        # ------------------------------------------------------------

        claim_hash = hashlib.sha256(
            canonical({
                "statement": statement,
                "source_a": source_a,
                "source_b": source_b
            }).encode()
        ).hexdigest()

        explanation_hash = hashlib.sha256(
            reason.encode()
        ).hexdigest()

        # ------------------------------------------------------------
        # STORE
        # ------------------------------------------------------------

        self.claims[claim_id] = Claim(
            creator=claim.creator,

            statement=claim.statement,
            source_a=claim.source_a,
            source_b=claim.source_b,

            status=status,
            confidence=u256(confidence),

            explanation_hash=explanation_hash,
            claim_hash=claim_hash
        )

        return status

    # ================================================================
    # GET CLAIM
    # ================================================================

    @gl.public.view
    def get_claim(self, claim_id: int) -> str:

        require(
            0 <= claim_id < len(self.claims),
            "claim does not exist"
        )

        c = self.claims[claim_id]

        return canonical({
            "claim_id": claim_id,
            "creator": c.creator,
            "statement": c.statement,
            "source_a": c.source_a,
            "source_b": c.source_b,
            "status": c.status,
            "confidence": int(c.confidence),
            "explanation_hash": c.explanation_hash,
            "claim_hash": c.claim_hash
        })

    @gl.public.view
    def claim_count(self) -> int:
        return len(self.claims)
