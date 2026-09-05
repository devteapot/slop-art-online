#!/usr/bin/env python3
"""Actual MCP stdio protocol calls to real actor-scoped authority. No model inference."""
import json,os,subprocess,sys,select,time
from pathlib import Path
session,stage,out=sys.argv[1:]
env={**os.environ,'SAO_PARTICIPANT_SESSION':session}
p=subprocess.Popen(['target/debug/sao-agent-mcp'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
seq=0
meta={'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientInfo':{'name':'sao-protocol-verifier','version':'1'},'io.modelcontextprotocol/clientCapabilities':{}}
def rpc(method,params):
 global seq
 seq+=1
 p.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':{**params,'_meta':meta}})+'\n');p.stdin.flush()
 deadline=time.monotonic()+15
 while time.monotonic()<deadline:
  if not select.select([p.stdout],[],[],max(0,deadline-time.monotonic()))[0]: break
  line=p.stdout.readline()
  if not line: raise RuntimeError('MCP process exited: '+p.stderr.read()[:2000])
  response=json.loads(line)
  if response.get('id')==seq:
   assert 'error' not in response,response
   return response['result']
 raise TimeoutError(method)
def call(name,args):
 r=rpc('tools/call',{'name':name,'arguments':args})
 if 'structuredContent' in r:return r,r['structuredContent']
 for c in r.get('content',[]):
  if c.get('type')=='text':return r,json.loads(c['text'])
 raise AssertionError(r)
try:
 discovery=rpc('server/discover',{})
 assert '2026-07-28' in discovery['supportedVersions'],discovery
 tools=rpc('tools/list',{})
 assert {t['name'] for t in tools['tools']}=={'observe','replace_tree','patch_subtree','speak','reflect'}
 _,v=call('observe',{'after_cursor':0,'limit':256})
 assert v['actor']==2 and v['api_version']=='sao-participant-v1'
 assert 'hazard' not in json.dumps(v) and 'sites' not in v and 'pending' not in v
 if stage=='setup':
  common={'control_epoch':v['control_epoch']}
  _,r=call('replace_tree',{**common,'request_id':'mcp-tree-fixture','expected_revision':v['policy_revision'],'reason':'explicit protocol parity fixture','tree':{'kind':'action','action':{'skill':'move','destination':5,'duration':1}}});assert r['ok'],r
  _,stale=call('patch_subtree',{**common,'request_id':'mcp-stale-fixture','expected_revision':v['policy_revision'],'reason':'stale fixture must reject','path':'root','subtree':{'kind':'action','action':{'skill':'wait','duration':1}}});assert not stale['ok'] and 'stale' in stale['error']
  _,receipt=call('speak',{**common,'request_id':'mcp-speech-fixture','text':'Protocol parity fixture words','expires_tick':10});assert receipt['ok']
  _,again=call('speak',{**common,'request_id':'mcp-speech-fixture','text':'Protocol parity fixture words','expires_tick':10});assert receipt==again
  source=next(e['source'] for e in v['experiences'] if e['kind']=='perception' and e['data']['kind']=='site')
  _,r=call('reflect',{**common,'request_id':'mcp-learning-fixture','expected_revision':v['learning_revision'],'observed_cursor':v['latest_cursor'],'reflections':[{'source':source,'interpretation':'Explicit fixture interpretation','caution_delta':2,'trust_delta':0,'belief':None}],'goal':'Fixture evidence comparison'});assert r['ok'],r
 _,v=call('observe',{'after_cursor':0,'limit':256})
 Path(out).write_text(json.dumps({'protocol':'2026-07-28','transport':'stdio','sdk':'rmcp 3.2.0','stage':stage,'discovery':discovery,'tools':[t['name'] for t in tools['tools']],'snapshot':v},indent=2)+'\n')
 print('MCP protocol and actor-scoped '+stage+' verified; no model inference')
finally:
 p.stdin.close()
 try:p.wait(timeout=3)
 except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=3)
