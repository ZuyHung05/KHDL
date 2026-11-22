"""Cleaning QA and conservative, auditable duplicate candidate generation."""
from __future__ import annotations
import argparse,csv,hashlib,html,json,os,re,sqlite3,tempfile,unicodedata
from collections import Counter,defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from bs4 import BeautifulSoup
import pyarrow as pa
import pyarrow.parquet as pq
from src.collection import runner
from . import unified,cleaning

ROOT=unified.ROOT
VERSION='dedup_v2'


def norm(text):return runner.normalized(text or '')


def norm_url(value):
    # Reuse M01 URL normalization; identity checks below are stricter.
    return runner.clean_url(value or '')


def topcv_posting_id(value):
    """TopCV's numeric posting ID in the job URL; never infer IDs elsewhere."""
    from urllib.parse import urlsplit
    try:
        url=urlsplit(value or '')
        if url.scheme.lower() not in ('http','https') or (url.hostname or '').lower() not in ('topcv.vn','www.topcv.vn'):
            return None
        match=re.fullmatch(r'/viec-lam/[^/]+/(\d+)\.html/?',url.path,flags=re.I)
        return match.group(1) if match else None
    except ValueError:return None


def text_value(row):
    for name in ('description_clean','raw_job_text_clean','description_transformed_clean'):
        text=row.get(name)
        if isinstance(text,str) and text.strip():return text
    return ''


def multi_issue(row):
    if row.get('source_id')!='awesome_jobs_vietnam':return False
    text=(row.get('job_title_clean') or '')+'\n'+(row.get('raw_job_text_clean') or '')
    return bool(re.search(r'(?i)\b(?:multiple\s+(?:positions|roles|vacancies)|several\s+(?:positions|roles|vacancies)|nhiều\s+vị\s+trí|(?:we\s+are\s+)?hiring\s+(?:for\s+)?\d+\s+(?:roles|positions)|\d+\s+(?:roles|positions|jobs))\b',text))


def compatible(a,b):
    ca,cb=norm(a.get('company_name')),norm(b.get('company_name'))
    if ca and cb and ca!=cb:return False
    la,lb=norm(a.get('location_raw')),norm(b.get('location_raw'))
    if la and lb and la!=lb:return False
    return True


def exact_keys(row):
    sid=row['source_id'];title=norm(row.get('job_title_clean'));company=norm(row.get('company_name'));url=norm_url(row.get('source_url'));loc=norm(row.get('location_raw'));text=norm(text_value(row));keys=[]
    # Job ID is never used without source, company and title; platform participates.
    source_id=norm(row.get('source_job_id'));platform=norm(row.get('platform'))
    if sid=='awesome_jobs_vietnam' and source_id:keys.append(('source_identity',sid,source_id))
    elif source_id and company and title:
        posting=norm(row.get('source_posting_id'))
        if sid!='careersgovsg' or platform not in ('workable','hrp') or posting:
            keys.append(('source_identity',sid,platform,source_id,posting,company,title))
    topcv_id=topcv_posting_id(row.get('source_url'))
    if topcv_id and title:
        keys.append(('topcv_posting_id',topcv_id,title))
    # A repeated template, even at the same employer, is not sufficient proof of
    # the same posting: require the same URL and full content fingerprint.
    if url and company and title and len(text)>=100:
        keys.append(('url_and_content',url,company,title,hashlib.sha256(text.encode()).hexdigest()))
    return keys


def select_rep(indices,records):
    def score(i):
        r=records[i];text=text_value(r);req=r.get('requirements_clean')
        if req:
            try:req=json.loads(req)
            except (TypeError,ValueError):req=None
        def content_length(value):
            if isinstance(value,str):return len(value.strip())
            if isinstance(value,list):return sum(content_length(item) for item in value)
            if isinstance(value,dict):return sum(content_length(item) for item in value.values())
            return 0
        sections=sum(bool(r.get(name)) for name in ('description_clean','requirements_clean','responsibilities_clean'))
        return (-int(bool(text.strip())),-sections,-(len(text)+content_length(req)+len(r.get('responsibilities_clean') or '')),-int(bool(r.get('company_name'))),-int(bool(norm_url(r.get('source_url')))),-int(bool(r.get('source_job_id'))),r['record_id'])
    return min(indices,key=score)


def exact_clusters(records):
    parent=list(range(len(records)));members={i:[i] for i in range(len(records))};key_index=defaultdict(list);edges=[]
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    # Stable order independent of input order.
    for i in sorted(range(len(records)),key=lambda x:records[x]['record_id']):
        for key in exact_keys(records[i]):
            for j in key_index[key]:
                a,b=find(i),find(j)
                if a==b:continue
                if not all(compatible(records[x],records[y]) for x in members[a] for y in members[b]):continue
                # Multiple-job issue bodies cannot be merged across issues based on shared content.
                if key[0]!='source_identity' and any(multi_issue(records[x]) for x in members[a]+members[b]):continue
                if records[a]['record_id']>records[b]['record_id']:a,b=b,a
                parent[b]=a;members[a].extend(members.pop(b));edges.append((i,j,key[0]))
            key_index[key].append(i)
    return sorted((sorted(v,key=lambda i:records[i]['record_id']) for v in members.values()),key=lambda v:records[v[0]]['record_id']),edges


def shingles(text):
    words=re.findall(r'\w+(?:[+#.]\w*)*',norm(text))
    return {' '.join(words[i:i+5]) for i in range(len(words)-4)}


def near_candidates(records,clusters,threshold=.80,max_block=250):
    # Candidates are restricted to shared title and same explicit employer, or same URL.
    # Blocks >250 are counted and not compared, to avoid unbounded quadratic work.
    blocks=defaultdict(list);reps=[select_rep(c,records) for c in clusters]
    for i in reps:
        r=records[i]; title=norm(r.get('job_title_clean'));company=norm(r.get('company_name'));url=norm_url(r.get('source_url'))
        if title and company:blocks[('company_title',company,title)].append(i)
        if url:blocks[('url',url)].append(i)
    pairs=set();skipped=0
    for values in blocks.values():
        values=sorted(set(values),key=lambda i:records[i]['record_id'])
        if len(values)>max_block:skipped+=1;continue
        for n,i in enumerate(values):
            for j in values[n+1:]:pairs.add((min(i,j),max(i,j)))
    cache={};out=[]
    for i,j in sorted(pairs,key=lambda x:(records[x[0]]['record_id'],records[x[1]]['record_id'])):
        a,b=records[i],records[j]
        if not compatible(a,b):continue
        for k in (i,j):
            if k not in cache:cache[k]=shingles(text_value(records[k]))
        sa,sb=cache[i],cache[j]
        if not sa or not sb:continue
        similarity=len(sa&sb)/len(sa|sb)
        if similarity>=threshold:out.append({'record_id_a':a['record_id'],'record_id_b':b['record_id'],'source_id_a':a['source_id'],'source_id_b':b['source_id'],'jaccard_5gram':round(similarity,6),'status':'needs_review','reason':'similar_text_not_merged'})
    return out,{'candidate_pairs_examined':len(pairs),'oversized_blocks_skipped':skipped,'threshold':threshold,'blocking':'exact normalized company + title or normalized URL','shingle_size':5,'limitations':'Candidates outside blocks and blocks over limit are not examined.'}


def visible_text(text):
    text=cleaning.unescape_all(text or '')
    if re.search(r'(?i)</?(?:p|div|span|li|ul|ol|h[1-6]|br|a|table)\b',text):
        text=BeautifulSoup(text,'html.parser').get_text(' ',strip=True)
    text=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',r'\1 \2',text)
    return text


def qa_review(row):
    details=[]
    for field in cleaning.FIELDS:
        orig=row.get(field);out=row.get(field+'_clean')
        if orig is None or out is None:continue
        try:
            before=json.loads(orig) if field=='requirements' else orig
            after=json.loads(out) if field=='requirements' else out
        except (ValueError,TypeError):
            details.append({'field':field,'finding':'needs_review_invalid_json'});continue
        if not isinstance(before,str) or not isinstance(after,str):continue
        before_tokens=re.findall(r'[\w+#.]+',norm(visible_text(before)))
        after_tokens=re.findall(r'[\w+#.]+',norm(after))
        # Conservative automated evidence; unaccounted words never declared markup-only.
        missing=Counter(before_tokens)-Counter(after_tokens)
        missing={k:v for k,v in missing.items() if k not in {'http','https','www'}}
        ratio=SequenceMatcher(None,before_tokens,after_tokens,autojunk=False).ratio() if before_tokens else 1.0
        details.append({'field':field,'original_chars':len(before),'clean_chars':len(after),'original_visible_tokens':len(before_tokens),'missing_token_count':sum(missing.values()),'sequence_similarity':round(ratio,4),'finding':'no_visible_token_loss_detected' if not missing else 'needs_review_visible_tokens_missing'})
    return details


def legacy_mapping(records):
    path=ROOT/'data/curated/role_classification/corpora/roles_v8/corpus.jsonl'
    if not path.exists():return {},{'status':'unavailable'}
    lookup={};count=0
    with path.open(encoding='utf-8') as f:
        for line in f:
            x=json.loads(line);count+=1
            for m in x['source_members']:
                k=(m['source_id'],m['file'],m['sha256'],m['row_index'])
                if k in lookup and lookup[k]!=x['jd_id']:raise ValueError('Conflicting Gemini source locator')
                lookup[k]=x['jd_id']
    mapping={}
    for row in records:
        loc=json.loads(row['source_locator']);k=(row['source_id'],row['source_file'],row['snapshot_sha256'],loc['row_index'])
        if k in lookup:mapping[row['record_id']]=lookup[k]
    db=ROOT/'data/curated/role_classification/state.sqlite'
    status_counts={}
    if db.exists():
        conn=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
        try:status_counts=dict(conn.execute("SELECT status,COUNT(*) FROM tasks WHERE run_id=? GROUP BY status",('gemini_full_v1',)).fetchall())
        finally:conn.close()
    return mapping,{'status':'available','baseline_unique_jd':count,'matched_records':len(mapping),'unmatched_records':len(records)-len(mapping),'method':'source_id, file, snapshot SHA-256 and zero-based row_index; not a direct label transfer','gemini_run':'gemini_full_v1','gemini_task_statuses_at_report':status_counts}


def run():
    src=ROOT/'data/staging/cleaned_jds.parquet';reportdir=ROOT/'data/reports';stage=ROOT/'data/staging'
    cleaning_report=runner.read_json(reportdir/'cleaning_report.json',{})
    src_hash=runner.sha256_file(src)
    if src_hash!=cleaning_report.get('output_sha256'):raise ValueError('Cleaned parquet checksum does not match cleaning report')
    table=pq.read_table(src);records=table.to_pylist();ids=[r['record_id'] for r in records]
    if len(set(ids))!=len(ids) or any(not x for x in ids):raise ValueError('Invalid record IDs')
    flagged=[r for r in records if any(x.startswith('large_reduction:') for x in r['cleaning_flags'])]
    # Review all flagged records and an additional deterministic sample of up to 5 per source.
    samples=[]
    for sid in sorted({r['source_id'] for r in records}):
        sample=sorted((r for r in records if r['source_id']==sid and r not in flagged),key=lambda r:hashlib.sha256(('qa42'+r['record_id']).encode()).hexdigest())[:5]
        samples.extend(sample)
    qa=[]
    for kind,items in (('large_reduction',flagged),('stratified_sample',samples)):
        for r in items:
            details=qa_review(r);qa.append({'record_id':r['record_id'],'source_id':r['source_id'],'sample_type':kind,'cleaning_flags':r['cleaning_flags'],'fields':details,'finding':'needs_review' if any(x['finding'].startswith('needs_review') for x in details) else 'no_visible_token_loss_detected','review_method':'automated token comparison; not human annotation'})
    legacy,legacy_info=legacy_mapping(records)
    clusters,edges=exact_clusters(records);edge_by=defaultdict(set)
    for i,j,reason in edges:edge_by[i].add(reason);edge_by[j].add(reason)
    mapping=[];representatives=[];representative_indices=[];group_sizes=Counter();conflicting_legacy=0
    for cluster in clusters:
        rep=select_rep(cluster,records);rep_row=records[rep];group_sizes[len(cluster)]+=1
        cluster_id=hashlib.sha256((VERSION+'\0'+min(records[i]['record_id'] for i in cluster)).encode()).hexdigest()
        prior=sorted({legacy[records[i]['record_id']] for i in cluster if records[i]['record_id'] in legacy})
        if len(prior)>1:conflicting_legacy+=1
        members=[{'record_id':records[i]['record_id'],'source_id':records[i]['source_id'],'source_file':records[i]['source_file'],'snapshot_sha256':records[i]['snapshot_sha256'],'source_locator':records[i]['source_locator']} for i in cluster]
        representatives.append({**rep_row,'jd_id':cluster_id,'member_count':len(cluster),'members_json':json.dumps(members,ensure_ascii=False,sort_keys=True),'legacy_gemini_jd_ids_json':json.dumps(prior)})
        representative_indices.append(rep)
        for i in cluster:
            r=records[i];mapping.append({'record_id':r['record_id'],'jd_id':cluster_id,'representative_record_id':rep_row['record_id'],'source_id':r['source_id'],'source_file':r['source_file'],'snapshot_sha256':r['snapshot_sha256'],'source_locator':r['source_locator'],'status':'representative' if i==rep else 'merged_exact','merge_reasons':sorted(edge_by[i] or ({'cluster_transitive'} if len(cluster)>1 else {'unique'})),'multi_position_issue':multi_issue(r),'issue_may_contain_multiple_positions':r['source_id']=='awesome_jobs_vietnam','gemini_legacy_jd_id':legacy.get(r['record_id'])})
    near,near_meta=near_candidates(records,clusters)
    if len(mapping)!=len(records) or len({x['record_id'] for x in mapping})!=len(records):raise ValueError('Input mapping is not one-to-one')
    if runner.sha256_file(src)!=src_hash:raise ValueError('Cleaned input changed during run')
    map_schema=pa.schema([('record_id',pa.string()),('jd_id',pa.string()),('representative_record_id',pa.string()),('source_id',pa.string()),('source_file',pa.string()),('snapshot_sha256',pa.string()),('source_locator',pa.string()),('status',pa.string()),('merge_reasons',pa.list_(pa.string())),('multi_position_issue',pa.bool_()),('issue_may_contain_multiple_positions',pa.bool_()),('gemini_legacy_jd_id',pa.string())])
    representative_table=table.take(pa.array(representative_indices,type=pa.int64()))
    for name,typ in (('jd_id',pa.string()),('member_count',pa.int64()),('members_json',pa.string()),('legacy_gemini_jd_ids_json',pa.string())):
        if name in representative_table.column_names:raise ValueError('Representative field already exists: '+name)
        representative_table=representative_table.append_column(name,pa.array([r[name] for r in representatives],type=typ))
    for target,tab in ((stage/'deduplicated_jds.parquet',representative_table),(stage/'duplicate_mapping.parquet',pa.Table.from_pylist(mapping,schema=map_schema))):
        fd,temp=tempfile.mkstemp(prefix='.dedup-',suffix='.parquet',dir=target.parent);os.close(fd)
        try:pq.write_table(tab,temp,compression='snappy');os.replace(temp,target)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    with (reportdir/'near_duplicate_candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['record_id_a','record_id_b','source_id_a','source_id_b','jaccard_5gram','status','reason']);writer.writeheader();writer.writerows(near)
    qa_counts=Counter(x['finding'] for x in qa)
    qareport={'generated_at':runner.now(),'input_sha256':src_hash,'review_method':'automated comparison performed by agent; no human review','large_reduction_count':len(flagged),'stratified_sample_count':len(samples),'sample_method':'up to 5 per source excluding large-reduction, hash seed qa42','finding_counts':dict(qa_counts),'records':qa,'limitations':['Token equality does not establish semantic equivalence.','Records marked needs_review require human inspection; no automated correction or exclusion.']}
    runner.write_json(reportdir/'cleaning_qa_report.json',qareport)
    legacy_to_new=defaultdict(set)
    for item in mapping:
        if item['gemini_legacy_jd_id']:legacy_to_new[item['gemini_legacy_jd_id']].add(item['jd_id'])
    report={'generated_at':runner.now(),'version':VERSION,'input_sha256':src_hash,'input_records':len(records),'output_jds':len(clusters),'duplicate_clusters':sum(n for size,n in group_sizes.items() if size>1),'merged_records':len(records)-len(clusters),'cluster_size_distribution':dict(sorted(group_sizes.items())),'multi_position_issue_count':sum(x['multi_position_issue'] for x in mapping),'issues_requiring_multiple_position_review':sum(x['issue_may_contain_multiple_positions'] for x in mapping),'exact_merge_reasons':dict(Counter(e[2] for e in edges)),'near_candidates':len(near),'near_method':near_meta,'legacy_gemini':{**legacy_info,'clusters_with_multiple_legacy_ids':conflicting_legacy,'legacy_ids_spanning_multiple_new_jds':sum(len(x)>1 for x in legacy_to_new.values())},'definitions':{'exact':'same TopCV numeric posting ID and title, same source identity, or same URL + company + title + full content fingerprint; all cluster members must have compatible explicit employer/location','representative':'prefer main text, more populated content sections, longer combined text, company, URL, source ID, then smallest record_id','limitations':'Absent employer or stable identity prevents automatic merge. Reused identifiers may need human review.'}}
    runner.write_json(reportdir/'dedup_report.json',report)
    print(json.dumps({'input':len(records),'jds':len(clusters),'merged':len(records)-len(clusters),'near_candidates':len(near),'qa':dict(qa_counts),'legacy':report['legacy_gemini']},ensure_ascii=False,indent=2))
    return report


def main():argparse.ArgumentParser(description=__doc__).parse_args();run()
if __name__=='__main__':main()
