from contextlib import contextmanager
from pathlib import Path
import tempfile
import json
import textwrap

from career_kit.paths import ProjectPaths
from career_kit.workflows import Workflows
from career_kit.store import utc_now
from career_kit.canonical_json import canonical_sha256


@contextmanager
def workspace():
    source = ProjectPaths.discover(Path(__file__))
    parent = source.runtime_path("work/tests"); parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        root = Path(directory)
        (root / ".career-kit.json").write_text('{"project":"career-kit","format_version":1}')
        paths = ProjectPaths(root)
        paths.initialize_runtime()
        yield paths


def setup(paths):
    flow = Workflows(paths)
    data = {
        "profile": {"display_name": "Synthetic Applicant", "email": "synthetic-email-token", "phone": "synthetic-phone-token", "location": "Synthetic Place"},
        "facts": {"facts": [{"id": "fact-example", "text": "Built a synthetic event processor.", "language": "en",
            "source_ref": "project-example/Q01", "category": "technical", "model_visible": True,
            "allowed_outputs": ["resume", "cover_letter", "match", "interview"]}]},
        "history": {"projects": [{"id": "project-example", "narrative": "Entirely synthetic example.", "interview": []}]},
        "preferences": {"company_blacklist": [], "quota": None},
    }
    for section, payload in data.items():
        revision = flow.candidate_import(section, payload)["revision"]
        flow.candidate_approve(section, revision)
    company = flow.company_propose({"name": "Synthetic Employer", "official_url": "https://employer.invalid", "evidence": "Synthetic fixture only"})
    flow.company_review(company["id"], company["revision"], "approved")
    job = {"company_id": company["id"], "requisition_id": "example-role", "title": "Synthetic Role",
           "description": "Process synthetic events.", "source_url": "https://employer.invalid/careers/example",
           "checked_at": utc_now(), "active": True, "requirements": [{"id": "central-events", "role_defining": True, "hard": False}]}
    mapping = {"job_hash": canonical_sha256(job), "facts_revision": flow.candidate("facts")["revision"],
               "requirements": [{"id": "central-events", "coverage": "direct", "fact_refs": ["fact-example"], "reason": "Matches synthetic evidence"}],
               "decision": "apply", "rationale": "Primary Agent selected a fictional example; no real application"}
    app = flow.application_create(job, mapping, "Synthetic test request")
    return flow, job, mapping, app


def profile(paths, identifier="text-example", output="text", extra=""):
    root = paths.permanent("local/document-profiles/" + identifier); root.mkdir(parents=True)
    manifest = {"schema_version": 1, "id": identifier, "document_types": ["resume", "cover_letter"],
                "output": output, "languages": ["en"], "entrypoint": "render.py", "required_commands": [],
                "identity_fields": ["display_name"], "static_text": [], "maximum_pages": 1}
    (root / "profile.json").write_text(json.dumps(manifest))
    source = '''
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output-dir');a=p.parse_args()
d=json.loads(Path(a.input).read_text());lines=list(d['identity'].values())+[c['text'] for c in d['claims']]
'''
    if output == "text":
        source += "Path(a.output_dir,'document.txt').write_text('\\n'.join(lines)+" + repr(extra) + ")\n"
    else:
        source += '''
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
w=PdfWriter();page=w.add_blank_page(width=595,height=842)
font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
s=DecodedStreamObject();s.set_data(('BT /F1 12 Tf 50 780 Td '+ ' 0 -20 Td '.join('('+line+') Tj' for line in lines)+' ET').encode());page[NameObject('/Contents')]=w._add_object(s)
w.write(Path(a.output_dir,'document.pdf'))
'''
    (root / "render.py").write_text(textwrap.dedent(source))
    return root


def content(flow, app, kind="resume"):
    return {"application_id": app["id"], "document_type": kind, "language": "en",
            "facts_revision": flow.candidate("facts")["revision"],
            "claims": [{"text": "Built a synthetic event processor.", "fact_refs": ["fact-example"]}]}
