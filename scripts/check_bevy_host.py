#!/usr/bin/env python3
"""Read-only/static and enrollment boundary checks; never logs cookie values."""
import urllib.request,urllib.error,json,os
BASE=os.environ.get('BEVY_DEV_URL','http://127.0.0.1:18891')
def request(path,headers=None,body=None):
 req=urllib.request.Request(BASE+path,headers={"Content-Type":"application/json",**(headers or {})},data=json.dumps(body or {}).encode(),method='POST')
 try:
  with urllib.request.urlopen(req) as r:return r.status,r.read(),r.headers
 except urllib.error.HTTPError as e:return e.code,e.read(),e.headers
assert request('/api/session')[0]==403
assert request('/api/session',{'Origin':'https://untrusted.example','x-sao-client':'1'})[0]==403
assert request('/api/session',{'Origin':'null','x-sao-client':'1'})[0]==403
assert request('/api/session',{'Origin':BASE})[0]==403
assert request('/api/bind',{'Origin':BASE,'x-sao-client':'1'},{'identity':'0'*64})[0]==401
status,data,headers=request('/api/session',{'Origin':BASE,'x-sao-client':'1'})
assert status==200 and 'HttpOnly' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie']
assert set(json.loads(data))=={'db','server','run','mode','actor'}
if os.environ.get('BEVY_DEV_EXPECTED_DB_URL'):
 assert json.loads(data)['server']==os.environ['BEVY_DEV_EXPECTED_DB_URL']
print('Missing-origin/cross-origin/unauthenticated binding blocked; scoped HttpOnly session created without credential in response body')
