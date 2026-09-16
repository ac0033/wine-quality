"""Read-only independent review; writes only this review's evidence file."""
import csv,json,hashlib,math,statistics as st
from pathlib import Path
from collections import Counter,defaultdict
from decimal import Decimal
from datetime import datetime,timezone
R=Path(__file__).resolve().parents[2]
O=Path(__file__).parent
load=lambda p:json.loads((R/p).read_text(encoding='utf-8-sig'))
p=load('steps/01_数据预处理/1.1_原始数据理解与质量核验/outputs/data_profile.json')
e=load('steps/02_EDA/2.1_理化指标与quality的探索分析/outputs/eda.json')
s=load('steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/outputs/split_summary.json')
b=load('steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/outputs/baseline_validation.json')
checks=[]
def ck(name,a,z):
    ok=math.isclose(a,z,rel_tol=1e-10,abs_tol=1e-10) if isinstance(a,float) else a==z
    checks.append({'check':name,'passed':ok})
    if not ok: raise AssertionError((name,a,z))
def fp(f):
    raw=f.read_bytes();return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
protected={str(f.relative_to(R)):fp(f) for d in ['data','steps/01_data_understanding','steps/02_exploration','steps/03_prediction_design'] for f in (R/d).rglob('*') if f.is_file() and f.name!='report_rewrite.md'}
for path,v in s['inputs_before'].items():
    ck('input '+path,fp(R/path),{'bytes':v['bytes'],'sha256':v['sha256']})
def ranks(v):
    groups=defaultdict(list)
    for i,x in enumerate(v):groups[x].append(i)
    out=[0.0]*len(v);n=0
    for x,ids in sorted(groups.items()):
        rank=n+(len(ids)+1)/2
        for i in ids:out[i]=rank
        n+=len(ids)
    return out
def rho(a,z):return st.correlation(ranks(a),ranks(z))
def q(v,t):
    v=sorted(v);k=(len(v)-1)*t;i=int(k);return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(k-i)
with (R/'steps/03_数据划分/3.1_预测任务定义_固定划分与验证基线/outputs/split_assignments.csv').open(encoding='utf-8-sig',newline='') as f: ass=list(csv.DictReader(f))
summary={}
for wine in ['red','white']:
    with (R/f'data/winequality-{wine}.csv').open(encoding='utf-8-sig',newline='') as f:header,*raw=list(csv.reader(f,delimiter=';'))
    rows=[list(map(float,r)) for r in raw];y=[r[-1] for r in rows];n=len(rows);ep=e['files'][wine];pp=p['files'][wine]
    ck(wine+' header',header,pp['header']);ck(wine+' rows',n,pp['rows'])
    ck(wine+' valid',all(len(r)==12 and all(math.isfinite(v) for v in r) and r[-1].is_integer() and 0<=r[-1]<=10 for r in rows),True)
    counts=Counter(str(int(v)) for v in y);ck(wine+' counts',dict(counts),{k:v['rows'] for k,v in pp['quality_distribution'].items()})
    unique=list(dict.fromkeys(tuple(r) for r in raw));ck(wine+' duplicates',n-len(unique),pp['exact_duplicate_rows_beyond_first'])
    ur=[list(map(float,r)) for r in unique];deltas={}
    for j,h in enumerate(header):
        v=[r[j] for r in rows];ck(wine+h+' min',min(v),float(pp['ranges'][h]['min']));ck(wine+h+' max',max(v),float(pp['ranges'][h]['max']))
        if j==11:continue
        item=ep['indicators'][h]
        for key,val in {'valid_rows':n,'min':min(v),'q1':q(v,.25),'median':st.median(v),'q3':q(v,.75),'max':max(v),'mean':st.mean(v)}.items():ck(wine+h+key,val,item['distribution'][key])
        ck(wine+h+' pearson',st.correlation(v,y),item['pearson_quality']);rr=rho(v,y);ck(wine+h+' spearman',rr,item['spearman_quality'])
        for score,num in counts.items():
            vv=[r[j] for r in rows if r[-1]==int(score)]
            ck(wine+h+score+' grouped rows',len(vv),item['by_quality'][score]['rows']);ck(wine+h+score+' median',st.median(vv),item['by_quality'][score]['median'])
        delta=rho([r[j] for r in ur],[r[-1] for r in ur])-rr;deltas[h]=delta
        ck(wine+h+' sensitivity',delta,ep['sensitivity']['by_indicator'][h]['difference_unique_minus_all'])
        for k,h2 in enumerate(header[:-1]):ck(wine+h+h2+' pair',rho(v,[r[k] for r in rows]),ep['inter_indicator_spearman'][h][h2])
    wa=[a for a in ass if a['wine']==wine];ck(wine+' coverage',sorted(int(a['source_row']) for a in wa),list(range(1,n+1)))
    groups=defaultdict(list)
    for i,r in enumerate(raw,1):
        vals=[Decimal(t) for t in r[:11]];key='|'.join('0' if v==0 else format(v.normalize(),'f') for v in vals);groups[key].append(i)
    expected={};strata=defaultdict(list)
    for key,ids in groups.items():
        scores={y[i-1] for i in ids};ck(wine+' one score '+str(ids[0]),len(scores),1);strata[int(next(iter(scores)))].append(key)
    for score,keys in strata.items():
        ordered=sorted(keys,key=lambda k:(hashlib.sha256(f'20260914|{wine}|{score}|{k}'.encode()).hexdigest(),k));c=math.ceil(.2*len(keys))
        for rank,key in enumerate(ordered):
            split='final_evaluation' if rank<c else 'validation' if rank<2*c else 'training'
            gid=hashlib.sha256(f'{wine}|{key}'.encode()).hexdigest()
            for i in groups[key]:expected[i]=(gid,split)
    for a in wa:ck(wine+' assignment '+a['source_row'],(a['feature_group_id'],a['split']),expected[int(a['source_row'])])
    rowcounts=dict(Counter(a['split'] for a in wa));gc={split:len({a['feature_group_id'] for a in wa if a['split']==split}) for split in rowcounts}
    ck(wine+' split counts',rowcounts,s['files'][wine]['totals']['rows']);ck(wine+' group counts',gc,s['files'][wine]['totals']['feature_groups'])
    ty=[y[int(a['source_row'])-1] for a in wa if a['split']=='training'];vy=[y[int(a['source_row'])-1] for a in wa if a['split']=='validation']
    median=st.median(ty);mae=st.mean(abs(v-median) for v in vy);rmse=math.sqrt(st.mean((v-median)**2 for v in vy))
    for k,val in [('training_quality_median_prediction',median),('validation_mae',mae),('validation_rmse',rmse)]:ck(wine+k,val,b['files'][wine][k])
    summary[wine]={'rows':n,'counts':dict(counts),'duplicates_beyond_first':n-len(unique),'split_rows':rowcounts,'split_groups':gc,'baseline':{'prediction':median,'mae':mae,'rmse':rmse},'largest_sensitivity':max(deltas.items(),key=lambda t:abs(t[1])),'first_record':raw[0],'first_assignment':next(a for a in wa if a['source_row']=='1'),'same_as_first_record_rows':[i for i,r in enumerate(raw,1) if r==raw[0]]}
ck('total assignments',len(ass),6497)
for path,v in protected.items():ck('preservation '+path,fp(R/path),v)
result={'reviewed_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Independent standard-library recalculation; no model training and no final-evaluation errors','passed':len(checks),'total':len(checks),'summary':summary,'protected_files':protected,'checks':checks}
(O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':len(checks),'summary':summary},ensure_ascii=False,indent=2))
