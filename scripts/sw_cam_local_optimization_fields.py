"""Narrow parameter delta for existing rough/finish pairs; no native calls.

A sealed plan supplies actual identities, depth and pitch. This does not change
feature depth, tool, NC values, entry point, operation order or rest machining.
"""
from copy import deepcopy
from math import isfinite

ROUGH_SPECS=(
 ('first_depth','ICWRghMillOp','GetStartDepth','SetStartDepth','pair'),
 ('subsequent_depth','ICWRghMillOp','GetSubsequentDepthAmount','SetSubsequentDepthAmount','pair'),
 ('rough_final_depth','ICWRghMillOp','FinCutAmt','FinCutAmt','property'),
 ('spiral_pitch','ICWRghMillOp','GetSpiralPitch','SetSpiralPitch','feature'))
FINISH_SPECS=(
 ('first_depth','ICWFinishMillOp3','GetFirstDepthCut','SetFirstDepthCut','depth_pair'),
 ('max_depth','ICWFinishMillOp3','GetMaxDepthCut','SetMaxDepthCut','depth_pair'))

def require(v,msg):
 if not v:raise ValueError(msg)

def exact(a,b):
 if type(a)is not type(b):return False
 if type(a)is dict:return a.keys()==b.keys()and all(exact(a[k],b[k])for k in a)
 if type(a)is list:return len(a)==len(b)and all(exact(x,y)for x,y in zip(a,b))
 return a==b

def positive(v):return type(v)is float and isfinite(v)and v>0

def validate_plan(plan,targets,snapshot):
 require(set(plan)=={'scope','rows','maximum_GTP','maximum_Save','physical_cutting_conditions_qualified','production_qualified'},'Exact sealed optimization fields required')
 require(plan['scope']=='EXISTING_FOUR_DEPTH_AND_AIR_PITCH_V1'and type(plan['maximum_GTP'])is int and plan['maximum_GTP']==4 and type(plan['maximum_Save'])is int and plan['maximum_Save']==1,'Exactly four GTP and one Save maximum')
 require(plan['physical_cutting_conditions_qualified']is False and plan['production_qualified']is False,'Virtual optimization cannot approve physical cutting')
 require(type(targets)is list and len(targets)==4 and [t['operation_type']for t in targets]==[0,1,0,1],'Exactly two rough/finish pairs required')
 ids=[t['operation_native_id']for t in targets];require(all(type(i)is int and i>0 for i in ids)and len(set(ids))==4,'Four unique actual IDs required')
 require([t['feature_native_id']for t in targets][::2]==[t['feature_native_id']for t in targets][1::2]and targets[0]['feature_native_id']!=targets[2]['feature_native_id'],'Actual feature pairs differ')
 rows=plan['rows'];require(type(rows)is list and len(rows)==4 and [r['operation_native_id']for r in rows]==ids,'Exact selected order required')
 params={r['operation_native_id']:r for r in snapshot['parameters']};require(len(params)==len(snapshot['parameters'])==12,'Saved12 groups required')
 for t,p in zip(targets,rows):
  keys={'operation_native_id','feature_native_id','operation_type','tool_native_id','depth_mm'}|({'spiral_pitch_mm'}if t['operation_type']==0 else set())
  require(set(p)==keys and all(exact(p[k],t[k])for k in ('operation_native_id','feature_native_id','operation_type')),'Plan identity/type differs')
  old=params[t['operation_native_id']];tool=old['tool'];depth=p['depth_mm']
  require(positive(depth)and positive(tool['mill']['EffCutlength']['raw'])and depth<=tool['mill']['EffCutlength']['raw'],'Full selected depth exceeds observed cutting length')
  require(type(p['tool_native_id'])is int and p['tool_native_id']==tool['generic']['native_id']==t['assigned_tool']['native_id'],'Assigned tool differs')
  require(abs(depth-old['levels']['levels']['machining_depth_native'])<=1e-12,'One level must equal observed feature depth, without changing the feature')
  nc=old['nc']['feeds_compensation'];require(type(nc['GetSpndlSpeed'])is float and nc['GetSpndlSpeed']==7100. and type(nc['XYFeed'])is float and nc['XYFeed']==35. and exact(nc['GetCNCComp'],0) and exact(nc['GetTlpComp'],1),'Retain exact observed7100/35 CAM1/CNC0')
  if t['operation_type']==0:
   e=old['rough']['entry'];require(e['GetEntryExitType']['raw']==4 and type(e['GetEntryExitType']['raw'])is int and e['GetSpiralRadius']['raw']==.1 and old['startpoints']['entry_type']==4 and old['startpoints']['count']==1,'Only the existing single-point spiral4 radius.1 may be accelerated')
   require(positive(p['spiral_pitch_mm'])and e['GetSpiralPitch']['raw']<p['spiral_pitch_mm']<=depth,'Bounded increased positive pitch required')
  else:
   require(exact(old['finish_fields']['final_depth'],0.)and exact(old['finish']['FinalDepthCut']['raw'],0.),'Finish FinalDepthCut0 is observed and assertion-only')
 return deepcopy(plan)

def desired_values(row):
 if row['operation_type']==0:return dict(first_depth=[False,row['depth_mm']],subsequent_depth=[False,row['depth_mm']],rough_final_depth=0.,spiral_pitch=row['spiral_pitch_mm'])
 return dict(first_depth=[row['depth_mm'],False],max_depth=[row['depth_mm'],False])

def project_parameters(before,plan):
 result=deepcopy(before);selected={r['operation_native_id']:r for r in plan['rows']}
 for p in result['parameters']:
  target=selected.get(p['operation_native_id'])
  if target is None:continue
  depth=target['depth_mm']
  if target['operation_type']==0:
   d=p['rough']['depth'];d['FirstDepthAmt']['raw']=depth;d['SbsqDepthAmt']['raw']=depth;d['FinCutAmt']['raw']=0.
   for key in ('GetStartDepth','GetSubsequentDepthAmount'):d[key].update(raw=[False,depth],is_percent=False,value_native=depth)
   p['rough']['entry']['GetSpiralPitch']['raw']=target['spiral_pitch_mm']
  else:
   for field,raw in [('first_depth','FirstDepthCut'),('max_depth','MaxDepthCut')]:p['finish_fields'][field]=[depth,False];p['finish'][raw]['raw']=depth
 return result

def verify_configured(before,after,plan):
 """Only declared parameter leaves and bounded stale-path status may differ."""
 wanted=project_parameters(before,plan);observed=deepcopy(after)
 require(exact(wanted['parameters'],observed['parameters']),'Optimization changed unrequested parameter/alias/NC/tool/entry fields')
 selected={r['operation_native_id']for r in plan['rows']};prior={o['native_id']:o for o in before['binding']['operations']};retained=[]
 for op in observed['binding']['operations']:
  if op['native_id']not in selected:continue
  old=prior[op['native_id']];require(type(op['toolpath_generated'])is bool,'Strict selected generated state required')
  require(exact(op['toolpath_record_counts'],old['toolpath_record_counts'])or exact(op['toolpath_record_counts'],[]),'Setter may retain or invalidate an old path, never introduce an unknown new path')
  require(not op['toolpath_generated']or exact(op['toolpath_record_counts'],old['toolpath_record_counts']),'Generated selected stream must retain its exact old count before GTP')
  retained.append(dict(operation_native_id=op['native_id'],generated=op['toolpath_generated'],record_counts=deepcopy(op['toolpath_record_counts'])))
  op['toolpath_generated']=old['toolpath_generated'];op['toolpath_record_counts']=deepcopy(old['toolpath_record_counts'])
 require(exact(observed['binding'],wanted['binding']),'Operation/feature/setup/order/tool/protected binding changed')
 return dict(selected_parameter_delta_verified=True,retained_or_invalidated_selected_paths=retained,old_path_not_accepted_for_new_recipe=True,production_qualified=False)


def verify_regenerated(configured,generated,targets,counts):
 """Explicit regeneration: compare actual configured status; never pretend empty."""
 selected={t['operation_native_id']for t in targets};require(set(counts)==selected,'All four GTP outcomes required')
 observed=deepcopy(generated);old={o['native_id']:o for o in configured['binding']['operations']}
 for op in observed['binding']['operations']:
  oid=op['native_id']
  if oid not in selected:continue
  wanted=counts[oid]
  require(type(wanted)is list and len(wanted)==1 and type(wanted[0])is int and 0<wanted[0]<=100000,'One bounded positive native stream required')
  require(op['toolpath_generated']is True and exact(op['toolpath_record_counts'],wanted),'Generated outcome differs from native count')
  op['toolpath_generated']=old[oid]['toolpath_generated'];op['toolpath_record_counts']=deepcopy(old[oid]['toolpath_record_counts'])
 require(exact(observed,configured),'GTP changed an unrequested binding, parameter or NC value; stop before Save')
 return dict(exact_parameters_verified=True,regenerated_selected_operations=len(selected),protected_definitions=17,NC_unchanged=True,physical_cutting_conditions_qualified=False)

def specs(target):return ROUGH_SPECS if target['operation_type']==0 else FINISH_SPECS

def field_value(row,spec):
 if 'rough'in row:return row['rough']['entry'if spec[0]=='spiral_pitch'else'depth'][spec[2]]['raw']
 return row['finish_fields'][spec[0]]

def action_names(targets):
 return [str(t['operation_native_id'])+':'+s[0]for t in targets for s in specs(t)]+['GTP:'+str(t['operation_native_id'])for t in targets]+['SaveActiveDocument']
