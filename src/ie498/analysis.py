import json
import math
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/ie498-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from .environment import Market
from .storage import atomic_json,budget_label


def metrics(history, window=50, epsilon=.02, ci_threshold=.5, price_fraction=.8):
    if not history:
        return {}
    rows=history[-window:]
    prices=np.array([r['prices'] for r in rows]);profits=np.array([r['profits'] for r in rows])
    b=Market().benchmarks();n=sum(b['nash_profit']);m=sum(b['joint_profit'])
    ci=float((profits.sum(axis=1).mean()-n)/(m-n))
    fraction=float(np.all(prices>np.array(b['nash_price'])+epsilon,axis=1).mean())
    return dict(n_eval=len(rows),price_0=float(prices[:,0].mean()),price_1=float(prices[:,1].mean()),
                profit_0=float(profits[:,0].mean()),profit_1=float(profits[:,1].mean()),
                joint_profit=float(profits.sum(axis=1).mean()),CI=ci,
                price_std=float(prices.std(axis=0).mean()),price_gap=float(np.abs(prices[:,0]-prices[:,1]).mean()),
                price_fraction=fraction,price_success=fraction>=price_fraction,profit_success=ci>=ci_threshold,
                effective_success=fraction>=price_fraction and ci>=ci_threshold)


def wilson(k,n):
    if not n:return (None,None)
    z=1.95996398454;p=k/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0,mid-half),min(1,mid+half)


def bootstrap(values,seed=498):
    x=np.asarray(values,dtype=float)
    if len(x)<2:return (None,None)
    rng=np.random.default_rng(seed)
    draws=rng.choice(x,size=(5000,len(x)),replace=True).mean(axis=1)
    return tuple(float(y) for y in np.quantile(draws,[.025,.975]))


def condition_summary(g,mode,h):
    k=int(g.effective_success.sum());n=len(g);lo,hi=wilson(k,n);cl,ch=bootstrap(g.CI)
    aggregate=dict(mode=mode,H=int(h),n=n,successes=k,success_rate=k/n,wilson_low=lo,wilson_high=hi,
                       mean_CI=float(g.CI.mean()),CI_bootstrap_low=cl,CI_bootstrap_high=ch,
                       mean_price=float((g.price_0+g.price_1).mean()/2),mean_joint_profit=float(g.joint_profit.mean()))
    for metric in ('price_0','price_1','profit_0','profit_1','joint_profit','price_std','price_gap'):
        low,high=bootstrap(g[metric])
        aggregate.update({f'{metric}_mean':float(g[metric].mean()),f'{metric}_bootstrap_low':low,f'{metric}_bootstrap_high':high})
    for success in ('price_success','profit_success'):
        successes=int(g[success].sum());low,high=wilson(successes,n)
        aggregate.update({success+'_count':successes,success+'_rate':successes/n,
                          success+'_wilson_low':low,success+'_wilson_high':high})
    return aggregate


def analyze(store,destination):
    out=Path(destination);out.mkdir(parents=True,exist_ok=True)
    runs=store.rows('SELECT * FROM runs ORDER BY id')
    has_epochs=bool(store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_epochs'"))
    summary=[];long=[];resources=[];sensitivity=[];memory_audit=[]
    bench=Market().benchmarks();atomic_json(out/'benchmarks.json',bench)
    for run in runs:
        c=json.loads(run['config']);history=store.history(run['id'])
        owned=[r for r in history if r['t']>run['checkpoint']]
        row={k:run[k] for k in ('id','status','error','parent','checkpoint','commit_hash','prompt_hash')}
        epochs=store.rows('SELECT DISTINCT commit_hash FROM execution_epochs WHERE run_id=?',(run['id'],)) if has_epochs else []
        row['execution_commits']=';'.join(sorted({run['commit_hash']}|{e['commit_hash'] for e in epochs}))
        row.update({k:c[k] for k in ('stage','provider','model','architecture','H','mode','T')})
        row['repetition']=c.get('repetition')
        row['rounds_completed']=len(history);row['new_rounds']=len(owned)
        row.update(metrics(owned,c['evaluation_window'],c['epsilon_price'],c['ci_threshold'],c['price_fraction']))
        complete_live=run['status']=='completed' and c['provider']=='openai' and len(owned)==c['T']
        row['eligible_primary']=complete_live and c['stage']=='formation' and c['architecture']=='bullet_memory'
        row['eligible_reference']=complete_live and c['stage']=='formation_reference' and c['architecture']=='paper_reference' and c['H']==100 and c['mode']=='full'
        summary.append(row)
        for r in owned:
            for i in range(2):
                long.append(dict(run=run['id'],stage=c['stage'],t=r['t'],agent=i,price=r['prices'][i],
                                 proposed_price=r['proposed_prices'][i],quantity=r['quantities'][i],profit=r['profits'][i],
                                 shock_flag=r['shock_flags'][i],ceiling_exceeded=r['ceiling_exceeded'][i]))
        attempts=store.rows('SELECT * FROM api_attempts WHERE run_id=?',(run['id'],))
        views=[json.loads(r['payload']) for r in store.rows('SELECT payload FROM memory_views WHERE run_id=?',(run['id'],))]
        usage=[json.loads(a['usage'] or '{}') for a in attempts]
        final_archives=[store.archive(run['id'],i) for i in range(2)]
        for entry in store.rows('SELECT t,agent,text,call_id FROM memory_entries WHERE run_id=? AND t>? ORDER BY t,agent',(run['id'],run['checkpoint'])):
            memory_audit.append(dict(run=run['id'],**entry,word_count=len(entry['text'][2:].split()),utf8_bytes=len(entry['text'].encode())))
        resources.append(dict(run=run['id'],stage=c['stage'],calls=len(attempts),
            seller_calls=sum(a['purpose']=='seller' for a in attempts),compressor_calls=sum(a['purpose']=='compressor' for a in attempts),
            retries=sum(a['attempt']>1 for a in attempts),uncertain=sum(a['status']=='uncertain' for a in attempts),
            input_tokens=sum(u.get('prompt_tokens',0) for u in usage),
            cached_input_tokens=sum(u.get('prompt_tokens_details',{}).get('cached_tokens',0) for u in usage),
            cache_write_tokens=sum(u.get('prompt_tokens_details',{}).get('cache_write_tokens',0) for u in usage),
            output_tokens=sum(u.get('completion_tokens',0) for u in usage),
            reasoning_tokens=sum(u.get('completion_tokens_details',{}).get('reasoning_tokens',0) for u in usage),
            cost_usd=sum(a['cost'] for a in attempts),
            history_token_upper_bound=sum(v['history_tokens'] for v in views),memory_token_upper_bound=sum(v['memory_tokens'] for v in views),
            max_archive_token_upper_bound=max((v['archive_tokens'] for v in views),default=0),
            final_archive_entries=sum(len(a) for a in final_archives),
            final_archive_bytes=sum(len('\n'.join(a).encode()) for a in final_archives),
            max_visible_memory_words=max((sum(len((line[2:] if line.startswith('- ') else line).split()) for line in v['text'].splitlines()) for v in views),default=0),
            compressor_input_tokens=sum(json.loads(a['usage'] or '{}').get('prompt_tokens',0) for a in attempts if a['purpose']=='compressor')))
        if row['eligible_primary']:
            for eps in (.01,.02,.04):
                for threshold in (.4,.5,.6):
                    sensitivity.append(dict(run=run['id'],epsilon=eps,ci_threshold=threshold,
                                            **metrics(owned,epsilon=eps,ci_threshold=threshold)))
    df=pd.DataFrame(summary);df.to_csv(out/'runs.csv',index=False)
    pd.DataFrame(long).to_csv(out/'rounds.csv',index=False)
    pd.DataFrame(resources).to_csv(out/'resources.csv',index=False)
    pd.DataFrame(memory_audit).to_csv(out/'memory_audit.csv',index=False)
    pd.DataFrame(sensitivity).to_csv(out/'threshold_sensitivity.csv',index=False)
    atomic_json(out/'status.json',{'spending':store.spending(),'runs':summary})
    groups=[];minimum=[]
    if not df.empty:
        primary=df[df.eligible_primary]
        for (mode,h),g in primary.groupby(['mode','H']):
            groups.append(condition_summary(g,mode,h))
        for mode in ('clear','full','compressed'):
            eligible=[g for g in groups if g['mode']==mode and g['success_rate']>=.8]
            best=min(eligible,key=lambda g:g['H']) if eligible else None
            minimum.append(dict(mode=mode,minimum_tested_effective_H=best['H'] if best else None,
                                evidence=best,interpretation='sample criterion; not a population threshold'))
    pd.DataFrame(groups).to_csv(out/'conditions.csv',index=False)
    atomic_json(out/'minimum_tested_effective_H.json',minimum)
    reference_groups,comparison_groups=_reference_tables(df,out)
    _plots(store,runs,out,groups,df,bench)
    paired=_paired(store,runs,out)
    complete=[r for r in summary if r['status']=='completed']
    text='# IE498 experiment results\n\n'
    text+=f"The database contains {len(runs)} planned runs, of which {len(complete)} are completed. The cost ledger is ${store.spending()['spent']:.6f}; budget: {budget_label(store.spending())}.\n\n"
    text+='Live experiments, mock, smoke, and pilot runs are labeled separately. Only completed formation runs enter the main matrix. Each complete duopoly run is an independent statistical unit; rounds within a run are not independent observations.\n\n'
    if groups:
        text+='| Mode | H | n | Success | Mean CI |\n|---|---:|---:|---:|---:|\n'
        text+='\n'.join(f"| {g['mode']} | {g['H']} | {g['n']} | {g['successes']}/{g['n']} | {g['mean_CI']:.3f} |" for g in groups)+'\n\n'
    else:
        text+='No live formation results are eligible for the main matrix yet. Mock or short smoke runs cannot establish supracompetitive pricing.\n\n'
    text+='## Added paper-reference comparison (H=100)\n\n'
    text+='This condition overwrites PLANS/INSIGHTS each round. It was added after inspecting the original three-repeat results; its five new formal runs are separate from pilots and from the 15-cell bullet-memory matrix. Repeat labels do not imply contemporaneous or paired sampling.\n\n'
    if reference_groups:
        text+='| Architecture | Memory | H | n | Success | Mean CI |\n|---|---|---:|---:|---:|---:|\n'
        text+='\n'.join(f"| {g['architecture']} | {g['condition']} | {g['H']} | {g['n']} | {g['successes']}/{g['n']} | {g['mean_CI']:.3f} |" for g in comparison_groups)+'\n\n'
    else:
        text+='No completed formal paper-reference runs are available yet; historical paper pilots are not substituted.\n\n'
    text+='See paper_reference_conditions.csv and paper_reference_comparison.csv for separate condition estimates and uncertainty intervals.\n\n'
    text+='See runs.csv for complete status, resources.csv for calls and resources, and benchmarks.json for numerical benchmarks. Success proportions use Wilson intervals; continuous metrics use run-level bootstrap intervals (none for n<2).\n\n'
    text+=f'Analyzed {len(paired)} completed child branches; see paired.csv for paired analysis.\n'
    (out/'results.md').write_text(text)
    return summary


def _reference_tables(df,out):
    references=[];comparison=[]
    if not df.empty:
        selected=df[df.eligible_reference | (df.eligible_primary & (df.H==100))]
        for (architecture,mode,h),group in selected.groupby(['architecture','mode','H']):
            aggregate=condition_summary(group,mode,h)
            aggregate.update(architecture=architecture,
                             condition='overwritten_plans_insights' if architecture=='paper_reference' else mode,
                             stage='formation_reference' if architecture=='paper_reference' else 'formation')
            comparison.append(aggregate)
            if architecture=='paper_reference':references.append(aggregate)
    # Include headers even before the new condition has completed any runs.
    columns=['architecture','condition','stage','mode','H','n','successes','success_rate',
             'wilson_low','wilson_high','mean_CI','CI_bootstrap_low','CI_bootstrap_high',
             'mean_price','mean_joint_profit']
    for name,rows in [('paper_reference_conditions.csv',references),('paper_reference_comparison.csv',comparison)]:
        extra=sorted({key for row in rows for key in row}-set(columns))
        pd.DataFrame(rows,columns=columns+extra).to_csv(out/name,index=False)
    return references,comparison


def _plots(store,runs,out,groups,df,b):
    trajectory_dir=out/'trajectories';trajectory_dir.mkdir(exist_ok=True)
    for run in runs:
        rows=store.history(run['id'])
        if not rows:continue
        c=json.loads(run['config']);t=[r['t'] for r in rows]
        p=np.array([r['prices'] for r in rows]);profit=np.array([r['profits'] for r in rows])
        fig,axes=plt.subplots(2,1,figsize=(9,6),sharex=True)
        for i in range(2):axes[0].plot(t,p[:,i],label=f'Firm {i+1}',alpha=.8)
        axes[0].axhline(b['nash_price'][0],color='black',ls='--',label='Nash')
        axes[0].axhline(b['joint_price'][0],color='red',ls=':',label='Joint optimum')
        axes[0].set_ylabel('Price');axes[0].legend(ncol=4,fontsize=8)
        axes[1].plot(t,profit.sum(axis=1),label='Joint profit')
        axes[1].axhline(sum(b['nash_profit']),color='black',ls='--')
        axes[1].axhline(sum(b['joint_profit']),color='red',ls=':')
        axes[1].set(xlabel='Round',ylabel='Joint profit')
        fig.suptitle(f"{run['id']} | {c['provider']} | {run['status']}");fig.tight_layout()
        fig.savefig(trajectory_dir/f"{run['id']}.png",dpi=140);plt.close(fig)
    if groups:
        g=pd.DataFrame(groups)
        fig,ax=plt.subplots(figsize=(8,4))
        pivot=g.pivot(index='mode',columns='H',values='mean_CI').reindex(['clear','full','compressed'])
        image=ax.imshow(pivot.values,aspect='auto',vmin=min(0,np.nanmin(pivot.values)),vmax=max(1,np.nanmax(pivot.values)),cmap='viridis')
        ax.set_xticks(range(len(pivot.columns)),pivot.columns);ax.set_yticks(range(3),pivot.index)
        ax.set(xlabel='History window H',title='Formation: mean run-level CI')
        for i in range(3):
            for j in range(len(pivot.columns)):
                if not np.isnan(pivot.iloc[i,j]):
                    color='black' if image.norm(pivot.iloc[i,j])>.55 else 'white'
                    ax.text(j,i,f'{pivot.iloc[i,j]:.2f}',ha='center',va='center',color=color)
        fig.colorbar(image,ax=ax,label='CI');fig.tight_layout();fig.savefig(out/'formation_heatmap.png',dpi=160);plt.close(fig)
        fig,ax=plt.subplots(figsize=(8,4))
        primary=df[df.eligible_primary]
        for idx,mode in enumerate(['clear','full','compressed']):
            part=primary[primary['mode']==mode]
            replicate=part.groupby('H').cumcount()
            counts=part.groupby('H')['id'].transform('size')
            positions=np.array([list((0,1,5,20,100)).index(h)+(idx-1)*.22 for h in part.H])
            positions=positions+(replicate.to_numpy()-(counts.to_numpy()-1)/2)*.045
            ax.scatter(positions,part.CI,label=mode,alpha=.75)
        ax.axhline(0,color='black',ls='--');ax.axhline(1,color='red',ls=':')
        ax.set_xticks(range(5),[0,1,5,20,100]);ax.set(xlabel='History window H',ylabel='Run-level CI');ax.legend()
        fig.tight_layout();fig.savefig(out/'run_points.png',dpi=160);plt.close(fig)


def _paired(store,runs,out):
    pairs=[];events=[];parents=[]
    for run in runs:
        c=json.loads(run['config'])
        if c['stage']=='formation' and c['architecture']=='bullet_memory' and c['H']==100 and c['mode']=='full' and run['status']!='cancelled_user':
            hist=store.history(run['id'])
            parents.append(dict(parent=run['id'],status=run['status'],checkpoint_available=len(hist)>=200,
                                eligible=len(hist)>=200 and metrics(hist[150:200]).get('effective_success',False)))
    pd.DataFrame(parents).to_csv(out/'parent_eligibility.csv',index=False)
    for run in runs:
        if not run['parent'] or run['status']!='completed':continue
        c=json.loads(run['config']);checkpoint=run['checkpoint']
        parent=store.history(run['parent']);child=store.history(run['id'])
        baseline=[r for r in parent if checkpoint<r['t']<=c['T']]
        follow=[r for r in child if r['t']>checkpoint]
        eligible=metrics(parent[max(0,checkpoint-50):checkpoint]).get('effective_success',False)
        if len(baseline)!=len(follow) or not follow:continue
        a=metrics(follow);b=metrics(baseline)
        pairs.append(dict(parent=run['parent'],child=run['id'],stage=c['stage'],H=c['H'],mode=c['mode'],eligible_parent=eligible,
                          delta_CI=a['CI']-b['CI'],delta_joint_profit=a['joint_profit']-b['joint_profit'],
                          effective_success=a['effective_success']))
        if c['stage']=='maintenance':
            failure=next((i+20 for i in range(len(follow)-19) if not metrics(follow[i:i+20])['effective_success']),None)
            pairs[-1].update(first_failed_20_round_window_end=failure,
                             survival_censored=failure is None,followup_rounds=len(follow))
        if c.get('shock'):
            agent=1-c['shock']['agent'];event=c['shock']['t']
            zero_shock=child[event-1]['proposed_prices'][c['shock']['agent']]==0
            diffs=[]
            for r,control in zip(follow,baseline):
                delta=r['prices'][agent]-control['prices'][agent]
                events.append(dict(parent=run['parent'],child=run['id'],event_time=r['t']-event,
                                   opponent_price_delta=delta,opponent_profit_delta=r['profits'][agent]-control['profits'][agent],zero_shock=zero_shock))
                if r['t']>event:diffs.append(delta)
            recovery=next((i+1 for i in range(len(diffs)-4) if all(abs(d)<.02 for d in diffs[i:i+5])),None)
            pairs[-1].update(recovery_time=recovery,response_rounds=sum(abs(d)>=.02 for d in diffs),
                             first_opponent_price_delta=diffs[0] if diffs else None,
                             zero_shock=zero_shock)
    pd.DataFrame(pairs).to_csv(out/'paired.csv',index=False)
    pd.DataFrame(events).to_csv(out/'shock_events.csv',index=False)
    # Aggregate within parent before summarizing independent parent units.
    if pairs:
        p=pd.DataFrame(pairs)
        if 'zero_shock' in p:
            zeros=p.zero_shock.fillna(False).astype(bool)
            p[zeros].to_csv(out/'zero_amplitude_shocks.csv',index=False)
            p=p[~zeros]
        grouped=p.groupby(['parent','stage','H','mode'],as_index=False)[['delta_CI','delta_joint_profit']].mean()
        grouped.to_csv(out/'parent_groups.csv',index=False)
        condition_rows=[]
        for (stage,h,mode),group in grouped.groupby(['stage','H','mode']):
            low,high=bootstrap(group.delta_CI)
            condition_rows.append(dict(stage=stage,H=int(h),mode=mode,n_parents=len(group),
                                       mean_delta_CI=float(group.delta_CI.mean()),bootstrap_low=low,bootstrap_high=high))
        pd.DataFrame(condition_rows).to_csv(out/'paired_conditions.csv',index=False)
    if events:
        e=pd.DataFrame(events);e=e[~e.zero_shock]
        if e.empty:return pairs
        fig,axes=plt.subplots(2,1,figsize=(8,6),sharex=True)
        grouped=e.groupby(['parent','event_time'])[['opponent_price_delta','opponent_profit_delta']].mean().reset_index()
        for parent,g in grouped.groupby('parent'):
            axes[0].plot(g.event_time,g.opponent_price_delta,label=parent)
            axes[1].plot(g.event_time,g.opponent_profit_delta,label=parent)
        for ax in axes:
            ax.axhline(0,color='black',ls='--');ax.axvline(0,color='red',ls=':')
        axes[0].set_ylabel('Opponent price minus control');axes[0].legend(fontsize=7)
        axes[1].set(xlabel='Rounds since execution shock',ylabel='Opponent profit minus control')
        fig.tight_layout();fig.savefig(out/'shock_response.png',dpi=150);plt.close(fig)
    return pairs
