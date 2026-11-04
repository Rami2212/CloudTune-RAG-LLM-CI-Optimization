"""Hosted complete-work adapter using the existing durable GitHub run ledger.

Event, queue and infrastructure policies use their explicit replay adapter;
manual dispatch is never labelled a native test of those trigger semantics.
"""
from __future__ import annotations

import base64
import json
import time

from evaluation.ci_executor import ForkExperiment, GitHubError, RunPending, verify_fork
from evaluation.repository_preparation import git_blob_sha1, workflow_doc, write_json_immutable
from .context import safe_path
from .registry import digest


class TreatmentFork(ForkExperiment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra = {}

    def provision(self, state, save):
        if state.get("fork_repo"):
            return super().provision(state, save)
        owner = self.gh.request("GET", "/user")["login"]
        # GitHub's create-fork endpoint accepts name. A separate immutable name
        # keeps legacy/other-study forks from being adopted or overwritten.
        # https://docs.github.com/en/rest/repos/forks#create-a-fork
        name = "ct-" + self.upstream.split("/")[-1][:35] + "-" + digest(self.evaluation_id.encode())[:12]
        expected = f"{owner}/{name}"
        try:
            self.gh.request("GET", "/repos/" + expected)
        except GitHubError as exc:
            if exc.code != 404:
                raise
        else:
            raise ValueError("Named fork exists without this state's positive creation proof; preserve it")
        if state.get("fork_creation_intent"):
            raise ValueError("Prior fork creation outcome is uncertain; do not replay POST")
        state["fork_creation_intent"] = expected
        save()
        created = self.gh.request("POST", f"/repos/{self.upstream}/forks", {"name": name, "default_branch_only": False})
        if created.get("full_name", "").casefold() != expected.casefold() or type(created.get("id")) is not int:
            raise ValueError("Named fork creation returned unexpected identity")
        state.update(fork_repo=created["full_name"], fork_id=created["id"], fork_owner=owner,
                     fork_created_by_evaluation=True)
        save()
        for _ in range(12):
            try:
                info = self.gh.request("GET", "/repos/" + expected)
                verify_fork(info, self.upstream, owner, expected_id=state["fork_id"])
                return
            except GitHubError as exc:
                if exc.code != 404:
                    raise
            time.sleep(5)
        raise RunPending("Named fork creation is pending; resume observation")

    def make_treatment_arm(self, state, arm, proposed, extra, save):
        self.extra = extra
        try:
            result = self.make_arm(state, arm, proposed, save)
            result["extra_files_sha256"] = {p: digest(v["after"]) for p,v in extra.items()}
            save()
            return result
        finally:
            self.extra = {}

    def _new_tree(self, fork, base, workflow, *, remove_workflows=()):
        if not self.extra:
            return super()._new_tree(fork, base, workflow, remove_workflows=remove_workflows)
        if remove_workflows:
            raise ValueError("Treatments cannot alter the common isolation harness")
        listing = self.gh.request("GET", f"/repos/{fork}/git/trees/{base}?recursive=1")
        if listing.get("truncated"):
            raise ValueError("Cannot verify treatment base tree")
        blobs = {r["path"]: r for r in listing["tree"] if r["type"] == "blob"}
        changes = {self.workflow_path: workflow}
        for path, change in self.extra.items():
            safe_path(path)
            if path.startswith(".github/workflows/") or path not in blobs:
                raise ValueError("Hosted additional edits must be frozen non-workflow inputs")
            if blobs[path]["mode"] not in {"100644", "100755"} or blobs[path]["sha"] != git_blob_sha1(change["before"]):
                raise ValueError("Treatment before bytes differ from pinned Git tree")
            changes[path] = change["after"]
        entries = []
        for path, raw in changes.items():
            sha = self.gh.request("POST", f"/repos/{fork}/git/blobs", {
                "encoding": "base64", "content": base64.b64encode(raw).decode()})["sha"]
            entries.append({"path": path, "type": "blob", "mode": blobs[path]["mode"], "sha": sha})
        return self.gh.request("POST", f"/repos/{fork}/git/trees", {"base_tree": base, "tree": entries})["sha"]

    def _verify_arm_tree(self, fork, common_tree, arm):
        base = self.gh.request("GET", f"/repos/{fork}/git/trees/{common_tree}?recursive=1")
        changed = self.gh.request("GET", f"/repos/{fork}/git/trees/{arm['tree']}?recursive=1")
        if base.get("truncated") or changed.get("truncated"):
            raise ValueError("Treatment tree is truncated")
        def entries(tree):
            return {r["path"]: (r["mode"], r["sha"]) for r in tree["tree"] if r["type"] == "blob"}
        old, new = entries(base), entries(changed)
        if set(old) != set(new):
            raise ValueError("Treatment unexpectedly added or removed files")
        allowed = {self.workflow_path, *self.extra}
        if any(old[p] != new[p] for p in old if p not in allowed):
            raise ValueError("Treatment changed an unapproved source file")
        for path, item in self.extra.items():
            if new[path] != (old[path][0], git_blob_sha1(item["after"])):
                raise ValueError("Treatment file differs from approved candidate bytes")
        if digest(self.gh.blob(fork, new[self.workflow_path][1])) != arm["workflow_sha256"]:
            raise ValueError("Hosted workflow bytes differ from approved arm")


def clear_owned_caches(experiment, state, save):
    """Cold control is confined to this positively identified study-owned fork."""
    if state.get("pending") or not state.get("fork_created_by_evaluation"):
        raise ValueError("Cache reset requires an owned fork with no pending dispatch")
    fork=state["fork_repo"]
    info=experiment.gh.request("GET","/repos/"+fork)
    verify_fork(info,experiment.upstream,state["fork_owner"],expected_id=state["fork_id"])
    if any(r.get("status")!="completed" for r in experiment.gh.all(f"/repos/{fork}/actions/runs","workflow_runs")):
        raise RunPending("Active fork jobs prevent an isolated cold-cache reset")
    caches=experiment.gh.all(f"/repos/{fork}/actions/caches","actions_caches")
    for cache in caches:
        if type(cache.get("id")) is not int:
            raise ValueError("Cache inventory has no immutable numeric identity")
        state.setdefault("cache_delete_intents",[]).append(cache["id"]);save()
        try:
            experiment.gh.request("DELETE",f"/repos/{fork}/actions/caches/{cache['id']}")
        except GitHubError as exc:
            if exc.code!=404:raise
    if experiment.gh.all(f"/repos/{fork}/actions/caches","actions_caches"):
        raise RunPending("Cache reset has not settled; no cold trial was dispatched")
    state["cache_reset_count"]=state.get("cache_reset_count",0)+1;save()


def run_hosted(snapshot, output, *, study_id, context, treatments, repetitions,
               github, required_jobs, admitted, cache_regime="uncontrolled"):
    """A rejected arm does not block another; all dispatch intent stays durable."""
    if cache_regime not in {"cold","warm","uncontrolled"}:
        raise ValueError("Unknown hosted cache regime")
    identity = {"study_id": study_id, "source_commit_sha": context["source_commit_sha"],"cache_regime":cache_regime,
                "context_sha256": digest(context), "repetitions": repetitions,
                "treatments": {arm: digest(p) for arm,p in treatments.items()}, "required_jobs": required_jobs}
    path = output / "hosted_state.json"
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["identity"] != identity:
            raise ValueError("Hosted source/candidate/configuration identity changed")
    else:
        state = {"identity": identity, "records": [], "arms": {}}
    def save():
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    experiment = TreatmentFork(github, repo_id=manifest["repo_id"], workflow_path=context["workflow_path"],
        source_sha=context["source_commit_sha"], original=context["original_workflow"].encode(),
        evaluation_id=study_id, max_wait_seconds=900, poll_seconds=15, evidence_root=output)
    original = (snapshot/"source/original.yml").read_bytes()
    if digest(original)!=context["workflow_sha256"]:
        raise ValueError("Hosted original differs from frozen source")
    experiment.original=original
    files = {r["path"]: r for r in context["files"]}
    effective = {"A": (original, {})}
    for arm, proposal in treatments.items():
        if arm not in admitted:
            continue
        changed = {r["path"]: r for r in proposal.get("files", [])}
        if any(p.startswith(".github/workflows/") and p != context["workflow_path"] for p in changed):
            raise ValueError("Multi-workflow treatment requires native event scenario, not serial hosting")
        workflow = changed[context["workflow_path"]]["content"].encode() if context["workflow_path"] in changed else original
        effective[arm] = (workflow, {p: {"before": files[p]["text"].encode(), "after": r["content"].encode()}
                                   for p,r in changed.items() if p != context["workflow_path"]})
    experiment.provision(state, save)
    experiment.prepare(state, save)
    for arm, (workflow, extra) in effective.items():
        experiment.make_treatment_arm(state, arm, workflow, extra, save)
    order = list(effective)
    budget=(repetitions+(1 if cache_regime=="warm" else 0))*len(effective)
    if cache_regime=="warm":
        if not state.get("warm_cache_initialized") and not state.get("pending"):
            clear_owned_caches(experiment,state,save)
            state["warm_cache_initialized"]=True;save()
        for arm in order:
            if any(r["arm"]==arm and r["repeat"]==0 for r in state["records"]):continue
            experiment.execute(state,save,arm=arm,repeat=0,required=required_jobs,max_total=budget)
        if any(not r.get("comparable") for r in state["records"] if r["repeat"]==0):
            raise ValueError("Warm-up failed its contract; warm measurements were not dispatched")
    for repeat in range(1, repetitions + 1):
        offset = (repeat - 1) % len(order)
        for arm in order[offset:] + order[:offset]:
            if any(r["arm"] == arm and r["repeat"] == repeat for r in state["records"]):
                continue
            if state.get("pending"):
                pending = state["pending"]
                arm, repeat = pending["arm"], pending["repeat"]
            elif cache_regime=="cold":
                clear_owned_caches(experiment,state,save)
            result = experiment.execute(state, save, arm=arm, repeat=repeat, required=state.get("required_names", required_jobs),
                                        max_total=budget)
            if not any(r["arm"] == arm and r["repeat"] == repeat for r in state["records"]):
                state["records"].append(result)
                save()
    state["measurements_finalized"] = True
    state["cleanup_status"] = "RETAINED_BY_CONFIGURATION"
    save()
    report = {"evidence_scope": "github_actions", "records": state["records"],
              "cache_regime":cache_regime,"cache_hits":"not_inferred_from_warmup",
              "fork_repo": state["fork_repo"], "cleanup_status": state["cleanup_status"],
              "admitted_arms": list(effective), "identity": identity}
    write_json_immutable(output / "hosted_report.json", report)
    return report
