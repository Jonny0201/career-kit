"""Read-only continuation hints; never approvals or external-effect authority."""
from .store import Store


def status(paths):
    store = Store(paths)
    integrity = store.verify()
    sections = {}
    for section, kind in (("profile", "candidate_profile"), ("history", "candidate_history"),
                          ("facts", "candidate_facts"), ("preferences", "preferences")):
        rows = store.list(kind)
        record = next((r for r in rows if r["id"] == section), None)
        sections[section] = {"status": record["payload"].get("status") if record else "missing",
                             "revision": record["revision"] if record else None}
        if section == "preferences": preferences = record["payload"] if record else {}
        if section == "facts": fact_count = len(record["payload"].get("facts", [])) if record else 0
    companies = store.list("company")
    seeds = store.list("company_seeds")
    batches = store.list("company_batch")
    grouped = {item["id"] for batch in batches if batch["payload"]["status"] in {"proposed", "reviewing"}
               for item in batch["payload"]["items"] if item.get("reviewable")}
    individual_reviews = [r for r in companies if r["payload"]["status"] == "proposed" and r["id"] not in grouped]
    apps = store.list("application")
    effects = [r for r in store.list("effect") if r["payload"].get("status") in {"claimed", "uncertain", "unknown"}]
    profiles = store.list("document_profile")
    documents = {r["id"]: r for r in store.list("document")}
    reviews = []
    for app in apps:
        for slot, ref in app["payload"].get("documents", {}).items():
            record = documents.get(ref["id"])
            if record and record["payload"].get("review") in {"pending", "revise"}:
                reviews.append({"application_id": app["id"], "slot": slot, "id": record["id"], "revision": record["revision"], "status": record["payload"]["review"]})
    search = preferences.get("company_search", {})
    next_actions = []
    if not integrity["ok"]: next_actions.append("inspect_local_integrity_orphans")
    if effects: next_actions.append("reconcile_uncertain_mail_before_any_resend")
    if any(r["status"] != "confirmed" for r in sections.values()): next_actions.append("complete_or_confirm_missing_candidate_sections")
    if not fact_count: next_actions.append("collect_user_confirmed_career_evidence")
    if not companies and not seeds and search.get("initial_list_status", "not_asked") == "not_asked": next_actions.append("ask_user_for_initial_company_list")
    if not any(c["payload"]["status"] == "approved" for c in companies):
        if seeds and any(s["payload"]["rows"] for s in seeds): next_actions.append("research_user_seed_rows_then_propose_batch")
        elif search.get("initial_list_status") == "provided": next_actions.append("import_the_users_existing_private_company_list")
        elif search.get("allow_discovery") is True: next_actions.append("discover_companies_from_confirmed_preferences")
        elif search.get("initial_list_status") == "deferred" or search.get("allow_discovery") is False: next_actions.append("company_setup_deferred_by_user")
        elif not individual_reviews and "ask_user_for_initial_company_list" not in next_actions:
            next_actions.append("ask_for_seed_list_or_permission_for_preference_based_discovery")
    if individual_reviews: next_actions.append("review_existing_company_proposals")
    if any(b["payload"]["status"] in {"proposed", "reviewing"} for b in batches): next_actions.append("review_or_resume_exact_company_batch")
    if not any(p["payload"].get("status") == "approved" for p in profiles): next_actions.append("configure_user_document_backend_before_rendering")
    if reviews: next_actions.append("present_current_final_documents_for_user_review")
    if any(a["payload"].get("submitted_at") is None for a in apps): next_actions.append("continue_existing_application_and_check_readiness")
    return {"ok": integrity["ok"], "advisory_only": True, "candidate_sections": sections, "fact_count": fact_count,
            "initial_list_status": search.get("initial_list_status", "not_asked"),
            "seed_batches": [{"id": r["id"], "revision": r["revision"], "rows": len(r["payload"]["rows"])} for r in seeds],
            "company_counts": {state: sum(r["payload"]["status"] == state for r in companies) for state in ("proposed", "approved", "rejected", "watchlist")},
            "pending_company_reviews": [{"id": r["id"], "revision": r["revision"]} for r in individual_reviews],
            "company_batches": [{"id": r["id"], "revision": r["revision"], "status": r["payload"]["status"],
                                  "reviewed_revision": r["payload"].get("reviewed_revision")} for r in batches],
            "applications": [{"id": a["id"], "revision": a["revision"], "status": a["payload"]["status"]} for a in apps],
            "pending_document_reviews": reviews, "uncertain_mail_effects": [{"id": e["id"], "status": e["payload"]["status"]} for e in effects],
            "mail_config_present": paths.permanent("credentials/mail.json").is_file(), "mail_setup_required_for_job_search": False,
            "next_actions": next_actions}
