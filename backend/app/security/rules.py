"""Secret-detection rules -- a deliberately TRIMMED port of gitleaks'
(https://github.com/gitleaks/gitleaks) rule set. gitleaks is MIT licensed
(https://github.com/gitleaks/gitleaks/blob/master/LICENSE); full credit to
the gitleaks project and contributors for the rule shapes this module
reimplements as plain dataclasses. This is NOT a dependency on the
gitleaks binary or its TOML config format (plan/RULES.md sec 1.3: no new
dependency) -- every rule here is a from-scratch Python regex written to
match the same publicly-documented credential shapes gitleaks' own rules
target.

**Deliberately trimmed, not exhaustive.** gitleaks ships 150+ rules
covering dozens of niche/vendor-specific token shapes (individual cloud
sub-services, CI systems, package registries, ...). Porting the long tail
would multiply the keyword-gate and regex surface (see scanner.py's
docstring on why the keyword gate exists at all) for marginal real-world
hit rate on the repositories Compass is built to analyze. This set (~25
rules) covers the credential families most likely to actually appear in a
real repository's history: a cloud provider (AWS), source-control tokens
(GitHub, GitLab), a team-chat platform (Slack), payment/AI/messaging API
keys (Stripe, Google, SendGrid, Twilio, OpenAI, Anthropic, npm), embedded
database credentials (Postgres/MySQL/MongoDB connection URIs), generic PEM
private keys, JWTs, and one generic high-entropy-assignment catch-all.
Extending this list later is a matter of adding another ``SecretRule``
entry -- never widen scope beyond what a session prompt calls for
(plan/RULES.md sec 1.4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretRule:
    """One detection rule.

    ``regex`` is matched against a single line's text (already stripped of
    its leading ``+``/diff marker -- see scanner.py). When the pattern has a
    capturing group, group(1) is treated as "the secret value" for the
    entropy check / fingerprint / redacted preview; otherwise the whole
    match (group(0)) is.

    ``entropy_threshold`` is ``None`` for a rule whose value shape is
    already specific enough not to need a randomness check (a fixed-prefix
    token, a PEM block, a JWT, a connection URI) -- when set, the captured
    value's Shannon entropy must ALSO exceed it, in addition to the regex
    match, before the rule counts as a hit.

    ``keywords`` are lowercase literal substrings, at least one of which
    MUST appear in the line (case-insensitively) before this rule's
    comparatively expensive regex is even attempted -- see scanner.py's
    keyword gate. Every rule's keyword set is chosen so that no realistic
    value shaped like its own regex could appear on a line without also
    containing at least one of them.
    """

    id: str
    description: str
    regex: re.Pattern[str]
    entropy_threshold: float | None
    keywords: tuple[str, ...]


def _rule(
    id_: str,
    description: str,
    pattern: str,
    *,
    entropy: float | None,
    keywords: tuple[str, ...],
) -> SecretRule:
    return SecretRule(
        id=id_,
        description=description,
        regex=re.compile(pattern),
        entropy_threshold=entropy,
        keywords=keywords,
    )


RULES: list[SecretRule] = [
    _rule(
        "aws-access-key-id",
        "AWS Access Key ID",
        r"\b((?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16})\b",
        entropy=None,
        keywords=("akia", "abia", "acca", "asia"),
    ),
    _rule(
        "aws-secret-access-key",
        "AWS Secret Access Key",
        r"(?i)aws(?:_|-)?secret(?:_|-)?access(?:_|-)?key['\"]?\s*[:=]\s*['\"]([A-Za-z0-9/+=]{40})['\"]",
        entropy=4.0,
        keywords=("aws_secret", "aws-secret", "awssecret"),
    ),
    _rule(
        "github-pat",
        "GitHub Personal Access Token (classic)",
        r"\b(ghp_[0-9A-Za-z]{36})\b",
        entropy=None,
        keywords=("ghp_",),
    ),
    _rule(
        "github-pat-fine-grained",
        "GitHub Fine-Grained Personal Access Token",
        r"\b(github_pat_[0-9A-Za-z_]{82})\b",
        entropy=None,
        keywords=("github_pat_",),
    ),
    _rule(
        "github-oauth-token",
        "GitHub OAuth Access Token",
        r"\b(gho_[0-9A-Za-z]{36})\b",
        entropy=None,
        keywords=("gho_",),
    ),
    _rule(
        "github-app-token",
        "GitHub App/Installation Token",
        r"\b((?:ghu|ghs)_[0-9A-Za-z]{36})\b",
        entropy=None,
        keywords=("ghu_", "ghs_"),
    ),
    _rule(
        "gitlab-pat",
        "GitLab Personal Access Token",
        r"\b(glpat-[0-9A-Za-z\-_]{20})\b",
        entropy=None,
        keywords=("glpat-",),
    ),
    _rule(
        "slack-token",
        "Slack Token",
        r"\b(xox[baprs]-[0-9A-Za-z\-]{10,48})\b",
        entropy=None,
        keywords=("xoxb-", "xoxa-", "xoxp-", "xoxr-", "xoxs-"),
    ),
    _rule(
        "slack-webhook",
        "Slack Incoming Webhook URL",
        r"(https://hooks\.slack\.com/services/[A-Za-z0-9+/]{6,14}/[A-Za-z0-9+/]{6,14}/[A-Za-z0-9+/]{16,32})",
        entropy=None,
        keywords=("hooks.slack.com",),
    ),
    _rule(
        "stripe-secret-key",
        "Stripe Secret Key",
        r"\b(sk_live_[0-9A-Za-z]{24,})\b",
        entropy=None,
        keywords=("sk_live_",),
    ),
    _rule(
        "stripe-restricted-key",
        "Stripe Restricted Key",
        r"\b(rk_live_[0-9A-Za-z]{24,})\b",
        entropy=None,
        keywords=("rk_live_",),
    ),
    _rule(
        "google-api-key",
        "Google API Key",
        r"\b(AIza[0-9A-Za-z\-_]{35})\b",
        entropy=None,
        keywords=("aiza",),
    ),
    _rule(
        "private-key-pem",
        "Private Key (PEM block)",
        r"(-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)",
        entropy=None,
        keywords=("-----begin",),
    ),
    _rule(
        "jwt",
        "JSON Web Token",
        r"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b",
        entropy=None,
        keywords=("eyj",),
    ),
    _rule(
        "postgres-connection-uri",
        "PostgreSQL Connection URI with embedded credentials",
        r"(postgres(?:ql)?://[^:\s'\"]+:[^@\s'\"]+@[^\s'\"]+)",
        entropy=None,
        keywords=("postgres://", "postgresql://"),
    ),
    _rule(
        "mysql-connection-uri",
        "MySQL Connection URI with embedded credentials",
        r"(mysql://[^:\s'\"]+:[^@\s'\"]+@[^\s'\"]+)",
        entropy=None,
        keywords=("mysql://",),
    ),
    _rule(
        "mongodb-connection-uri",
        "MongoDB Connection URI with embedded credentials",
        r"(mongodb(?:\+srv)?://[^:\s'\"]+:[^@\s'\"]+@[^\s'\"]+)",
        entropy=None,
        keywords=("mongodb://", "mongodb+srv://"),
    ),
    _rule(
        "sendgrid-api-key",
        "SendGrid API Key",
        r"\b(SG\.[0-9A-Za-z\-_]{22}\.[0-9A-Za-z\-_]{43})\b",
        entropy=None,
        keywords=("sg.",),
    ),
    _rule(
        "twilio-api-key",
        "Twilio API Key",
        r"\b(SK[0-9a-fA-F]{32})\b",
        entropy=None,
        keywords=("twilio",),
    ),
    _rule(
        "twilio-account-sid",
        "Twilio Account SID",
        r"\b(AC[0-9a-fA-F]{32})\b",
        entropy=None,
        keywords=("twilio",),
    ),
    _rule(
        "openai-api-key",
        "OpenAI API Key",
        r"\b(sk-[A-Za-z0-9]{20,})\b",
        entropy=None,
        keywords=("sk-",),
    ),
    _rule(
        "anthropic-api-key",
        "Anthropic API Key",
        r"\b(sk-ant-[A-Za-z0-9\-_]{20,})\b",
        entropy=None,
        keywords=("sk-ant-",),
    ),
    _rule(
        "npm-token",
        "npm Access Token",
        r"\b(npm_[0-9A-Za-z]{36})\b",
        entropy=None,
        keywords=("npm_",),
    ),
    _rule(
        "azure-storage-account-key",
        "Azure Storage Account Key",
        r"(?i)accountkey\s*=\s*([A-Za-z0-9+/]{86}==)",
        entropy=4.0,
        keywords=("accountkey",),
    ),
    _rule(
        "generic-high-entropy-assignment",
        "Generic High-Entropy Secret Assignment",
        r"(?i)\b(?:secret|token|passwd|password|api[_-]?key)\b['\"]?\s*[:=]\s*['\"]([A-Za-z0-9+/_\-]{16,})['\"]",
        entropy=3.5,
        keywords=("secret", "token", "passwd", "password", "api_key", "apikey", "api-key"),
    ),
]
"""~25 rules (session 10 Part A target). Order is not significant -- every
rule is evaluated independently against every candidate line."""
