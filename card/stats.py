"""Created by Lyon. (Ailton Rocha)

Números do card vindos da API do GitHub, com cache em cache/ para o job diário não refazer tudo.

GraphQL: repositórios próprios, contribuídos (dono, colaborador ou membro de organização), soma de
estrelas dos próprios, seguidores e commits (contributionsCollection, ano a ano desde a criação da
conta). REST /repos/{o}/{r}/stats/contributors: adições, remoções e commits do usuário no ramo padrão
de cada repositório; o GitHub responde 202 enquanto calcula, então a coleta roda em rodadas.

cache/loc.json guarda o resultado por repositório com a chave em sha256 do nome: o repositório do
perfil é público e não pode expor nome de repositório privado (nem no log do Actions). Só é refeito
quando o pushedAt muda. Repositórios com o mesmo commit no topo (cópias do mesmo histórico) contam uma
vez. cache/stats.json guarda os últimos números completos: sem token, ou com a API fora, valem eles.
Só biblioteca padrão: o workflow não instala nada.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

USER = "lyonzin"
TOKEN_ENV = "ACCESS_TOKEN"
API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "lyonzin-profile-card"
HTTP_TIMEOUT_S = 60
STATS_ROUNDS = 8  # passadas pelo /stats/contributors até ele sair do 202
ROUND_WAIT_S = 5
OK, ACCEPTED, NO_CONTENT = 200, 202, 204
KEY_PREVIEW = 12  # caracteres do hash mostrados nos avisos
CACHE_DIR = Path(__file__).resolve().parent / "cache"
LOC_CACHE = CACHE_DIR / "loc.json"
STATS_CACHE = CACHE_DIR / "stats.json"

PROFILE_QUERY = "query($login: String!) { user(login: $login) { createdAt followers { totalCount } } }"
REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { nameWithOwner pushedAt stargazerCount owner { login } defaultBranchRef { target { oid } } }
    }
  }
}"""


@dataclass(frozen=True)
class Stats:
    repos: int
    contributed: int
    stars: int
    commits: int
    followers: int
    additions: int
    deletions: int


def request_json(url: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    """GET (ou POST, com corpo) autenticado na API; devolve o status HTTP e o JSON (None sem corpo)."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Authorization": f"bearer {token}", "Accept": "application/vnd.github+json",
               "User-Agent": USER_AGENT, "X-GitHub-Api-Version": API_VERSION}
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    status, payload = request_json(f"{API}/graphql", token, {"query": query, "variables": variables})
    if status != OK or not payload or payload.get("errors"):
        detail = payload.get("errors") if payload else "sem corpo"
        raise RuntimeError(f"GraphQL respondeu HTTP {status}: {detail}")
    return payload["data"]


def fetch_repositories(token: str) -> tuple[list[dict[str, Any]], int]:
    """Repositórios ligados ao usuário (dono, colaborador, membro de organização), por nome, e o total."""
    nodes: list[dict[str, Any]] = []
    cursor = None
    while True:
        page = graphql(token, REPOS_QUERY, {"login": USER, "cursor": cursor})["user"]["repositories"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return sorted(nodes, key=lambda node: node["nameWithOwner"]), page["totalCount"]
        cursor = page["pageInfo"]["endCursor"]


def year_end(year: int, now: datetime) -> str:
    """Fim do intervalo de um ano: o último segundo dele, ou agora, no ano corrente."""
    return now.strftime("%Y-%m-%dT%H:%M:%SZ") if year == now.year else f"{year}-12-31T23:59:59Z"


def commits_query(created_at: str, now: datetime) -> str:
    """Um contributionsCollection por ano desde a criação da conta (a API limita cada intervalo a um ano)."""
    blocks = [
        f'y{year}: contributionsCollection(from: "{year}-01-01T00:00:00Z", to: "{year_end(year, now)}") '
        "{ totalCommitContributions }"
        for year in range(int(created_at[:4]), now.year + 1)
    ]
    return "query($login: String!) { user(login: $login) { " + " ".join(blocks) + " } }"


def fetch_commits(token: str, created_at: str, now: datetime) -> int:
    years = graphql(token, commits_query(created_at, now), {"login": USER})["user"]
    return sum(year["totalCommitContributions"] for year in years.values())


def repo_key(name_with_owner: str) -> str:
    return hashlib.sha256(name_with_owner.encode("utf-8")).hexdigest()


def unique_by_head(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Um repositório por commit no topo: cópias do mesmo histórico contam uma vez; vazios saem."""
    seen: set[str] = set()
    unique = []
    for repo in repos:
        head = ((repo.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
        if head and head not in seen:
            seen.add(head)
            unique.append(repo)
    return unique


def author_totals(contributors: list[dict[str, Any]] | None) -> dict[str, int]:
    """Adições, remoções e commits do usuário no /stats/contributors, somando as semanas."""
    for entry in contributors or []:
        if ((entry.get("author") or {}).get("login") or "").lower() == USER:
            weeks = entry.get("weeks", [])
            return {"additions": sum(week["a"] for week in weeks), "deletions": sum(week["d"] for week in weeks),
                    "commits": entry.get("total", 0)}
    return {"additions": 0, "deletions": 0, "commits": 0}


Repos = dict[str, dict[str, Any]]  # chave sha256 do nome -> dados do repositório (ou do cache)


def stats_round(token: str, pending: Repos, results: Repos) -> Repos:
    """Uma passada pelo /stats/contributors; grava os prontos em `results` e devolve os que seguem em 202."""
    still = {}
    for key, repo in pending.items():
        status, payload = request_json(f"{API}/repos/{repo['nameWithOwner']}/stats/contributors", token)
        if status == ACCEPTED:
            still[key] = repo
        elif status in (OK, NO_CONTENT):
            results[key] = {"pushed_at": repo["pushedAt"], **author_totals(payload)}
        else:
            print(f"aviso: stats/contributors HTTP {status} no repositório {key[:KEY_PREVIEW]}; fica de fora",
                  file=sys.stderr)
    return still


def fetch_loc(token: str, repos: list[dict[str, Any]], cache: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Linhas do usuário por repositório; reaproveita o cache quando o pushedAt não mudou."""
    results: dict[str, dict[str, Any]] = {}
    pending = {}
    for repo in unique_by_head(repos):
        key = repo_key(repo["nameWithOwner"])
        if cache.get(key, {}).get("pushed_at") == repo["pushedAt"]:
            results[key] = cache[key]
        else:
            pending[key] = repo
    for round_index in range(STATS_ROUNDS):
        if round_index:
            time.sleep(ROUND_WAIT_S)
        pending = stats_round(token, pending, results)
        if not pending:
            break
    for key in pending:  # o GitHub ainda calcula: fica o número antigo, e o pushedAt antigo força nova tentativa
        if key in cache:
            results[key] = cache[key]
    return results


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as error:
        print(f"aviso: {path.name} ilegível ({error}); recomeça do zero", file=sys.stderr)
        return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def collect(token: str) -> Stats:
    now = datetime.now(UTC)
    profile = graphql(token, PROFILE_QUERY, {"login": USER})["user"]
    repos, contributed = fetch_repositories(token)
    owned = [repo for repo in repos if repo["owner"]["login"].lower() == USER]
    loc = fetch_loc(token, repos, load_json(LOC_CACHE))
    save_json(LOC_CACHE, loc)
    return Stats(
        repos=len(owned), contributed=contributed, stars=sum(repo["stargazerCount"] for repo in owned),
        commits=fetch_commits(token, profile["createdAt"], now), followers=profile["followers"]["totalCount"],
        additions=sum(entry["additions"] for entry in loc.values()),
        deletions=sum(entry["deletions"] for entry in loc.values()),
    )


def cached_stats() -> Stats | None:
    try:
        return Stats(**load_json(STATS_CACHE)) if STATS_CACHE.exists() else None
    except TypeError as error:
        print(f"aviso: {STATS_CACHE.name} fora do formato ({error})", file=sys.stderr)
        return None


def get_stats() -> tuple[Stats | None, str]:
    """Números novos com token; sem token, ou com a API fora, os últimos do cache (ou None se não houver)."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        try:
            stats = collect(token)
            save_json(STATS_CACHE, asdict(stats))
            return stats, "API do GitHub"
        except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, ValueError) as error:
            print(f"aviso: API do GitHub indisponível ({type(error).__name__}: {error}); usando o cache",
                  file=sys.stderr)
    fallback = cached_stats()
    return fallback, "cache" if fallback else "sem dados"
