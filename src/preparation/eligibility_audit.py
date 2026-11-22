"""Reproduce a small, non-independent qualitative audit of inspected cases."""
import json
from collections import Counter
from pathlib import Path
import pyarrow.parquet as pq

# Hand-selected, inspected examples; unknown denotes unresolved scope, not ground truth.
CASES = {
'00062ade':'it', '001c2537':'it', '02726b35':'it', '03ca542d':'non_it',
'0009d663':'unknown', '00207ca4':'non_it',
'002287b5':'it', '0056469f':'it', '0b2469c3':'unknown', '1f15df54':'unknown',
'0036d1ec':'it', '0055ca0e':'it',
'03de7490':'it', '05f99061':'it',
'112a76d5':'non_it', '7fd9e3ea':'non_it',
'49791444':'non_it', '5053317f':'non_it',
}
REASON={
'00062ade':'Data engineering title; transformed text is not a complete JD.',
'001c2537':'AI engineering title and transformed text.',
'02726b35':'DWH/BI development title and data-engineering duties; Thailand location.',
'03ca542d':'Paid search marketing job, despite data analysis skills.',
'0009d663':'Data policy scope ambiguous for technical IT occupation.',
'00207ca4':'Parks management duties; not enough for IT.',
'002287b5':'Full stack software development responsibilities.',
'0056469f':'Backend software development role.',
'0b2469c3':'Teaching coding; whether the occupation belongs to IT needs a scope decision.',
'1f15df54':'Teaching Unity; scope of IT labor market needs review.',
'0036d1ec':'Frontend developer; issue remains unstructured.',
'0055ca0e':'Ruby on Rails developer; issue remains unstructured.',
'03de7490':'Embedded programming in C/C++; title-only systems engineer is ambiguous.',
'05f99061':'Security role includes penetration tests and cybersecurity duties.',
'112a76d5':'Accounting and tax duties.',
'7fd9e3ea':'Driving duties.',
'49791444':'Food/agriculture quality standards consulting.',
'5053317f':'Agricultural market development; application use alone is not IT work.',
}

def run():
 root=Path('.'); rows=pq.read_table(root/'data/staging/eligible_jds_v2.parquet').to_pylist(); cases=[]; confusion={'v1':Counter(),'v2':Counter()}
 for prefix, expected in CASES.items():
  matches=[r for r in rows if r['record_id'].startswith(prefix)]
  if len(matches)!=1: raise ValueError(prefix)
  r=matches[0]; item={'record_id':r['record_id'],'source_id':r['source_id'],'title':r['job_title_clean'],'v1_eligibility':r['v1_eligibility_status'],'v2_eligibility':r['eligibility_status'],'reference_domain':expected,'v1_domain':r['v1_domain_status'],'v2_domain':r['domain_status'],'reason':REASON[prefix]}; cases.append(item)
  for version in ('v1','v2'):confusion[version][expected+' -> '+item[version+'_domain']]+=1
 counts=Counter()
 pred=root/'data/curated/role_classification/runs/gemini_full_v1/predictions.jsonl'
 if pred.exists():
  for line in pred.open():
   try: counts[json.loads(line).get('status','missing')]+=1
   except json.JSONDecodeError:counts['incomplete_json_line']+=1
 report={'sampling':'18 hand-selected cases across all seven sources and all three v1 eligibility outcomes; convenience sample, not random or independent; adjudication by implementer, not a gold standard','dimension':'domain only; reference unknown means scope unresolved','confusion_rows_reference_columns_prediction':confusion,'cases':cases,'gemini_inventory_observed':counts,'gemini_decision':'Not used. Legacy dedup audit reports 254 legacy IDs split across M02 groups. Prediction entries contain source_members and content_hash but one-to-one member provenance, exact submitted content after transformations and conflicting labels have not been verified for transfer. Status PENDING is not a prediction. Counts may change during a running Gemini job.'}
 (root/'data/reports/eligibility_v2_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
