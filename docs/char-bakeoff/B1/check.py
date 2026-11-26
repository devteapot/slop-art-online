"""Check the delivered GLB against the shared clip rig and sample linear blend skinning."""
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'living/tools'))
import merge_primitives as glb

file,shared=map(Path,sys.argv[1:3])
doc,buf=glb.read_glb(file)
library,library_buf=glb.read_glb(shared)


def read(j,b,i):
    a=j['accessors'][i]
    vals,_=glb.read_accessor(j,b,i)
    return np.array(vals,dtype=float).reshape(a['count'],-1)


def channels(j,a):
    return {(j['nodes'][c['target']['node']]['name'],c['target']['path']) for c in a['channels']}


ids={n['name']:i for i,n in enumerate(doc['nodes'])}
parents={c:i for i,n in enumerate(doc['nodes']) for c in n.get('children',[])}
source_parents={c:n['name'] for n in library['nodes'] for c in n.get('children',[])}
shared_targets={name for a in library['animations'] for name,path in channels(library,a)}
missing=sorted(shared_targets-ids.keys())
assert not missing,missing
for i,n in enumerate(library['nodes']):
    if n['name'] in shared_targets:
        assert doc['nodes'][parents[ids[n['name']]]]['name']==source_parents[i]
mesh_node=next(n for n in doc['nodes'] if 'mesh' in n and any(
    doc['materials'][p['material']]['name']=='Undershirt'
    for p in doc['meshes'][n['mesh']]['primitives']))
skin=doc['skins'][mesh_node['skin']]
joints=skin['joints']
inverse=read(doc,buf,skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)


def rotation_matrix(q):
    x,y,z,w=np.asarray(q)/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
                     [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
                     [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])


def slerp(times,values,time):
    hi=min(len(times)-1,max(1,np.searchsorted(times,time)))
    t=(time-times[hi-1])/(times[hi]-times[hi-1])
    a,b=values[hi-1],values[hi]
    dot=np.dot(a,b)
    if dot<0:b=-b
    angle=np.arccos(min(1.,abs(dot)))
    if angle<1e-5:return (1-t)*a+t*b
    return (np.sin((1-t)*angle)*a+np.sin(t*angle)*b)/np.sin(angle)


def matrices(pose):
    cache={}
    def at(i):
        if i in cache:return cache[i]
        n=doc['nodes'][i]
        def value(key,default):return pose.get((n['name'],key),n.get(key,default))
        m=np.eye(4)
        m[:3,:3]=rotation_matrix(value('rotation',[0,0,0,1]))@np.diag(value('scale',[1,1,1]))
        m[:3,3]=value('translation',[0,0,0])
        cache[i]=at(parents[i])@m if i in parents else m
        return cache[i]
    return np.array([at(i) for i in joints])@inverse


primitives=[p for m in doc['meshes'] for p in m['primitives']]
body=[]
for p in primitives:
    if doc['materials'][p['material']]['name'] not in ('Undershirt','Shorts and socks','Rib knit','Exposed skin','Nail bed'):continue
    attr=p['attributes']
    pos=read(doc,buf,attr['POSITION'])
    idx=read(doc,buf,p['indices']).astype(int).reshape(-1,3)
    edges=np.unique(np.sort(np.concatenate([idx[:,[0,1]],idx[:,[1,2]],idx[:,[2,0]]]),axis=1),axis=0)
    length=np.linalg.norm(pos[edges[:,0]]-pos[edges[:,1]],axis=1)
    hit=length>1e-5
    ws=read(doc,buf,attr['WEIGHTS_0'])
    assert np.max(abs(ws.sum(axis=1)-1))<1e-5
    body.append((pos,read(doc,buf,attr['JOINTS_0']).astype(int),ws,edges[hit],length[hit]))


def deform(pos,indices,ws,mats):
    xyz1=np.c_[pos,np.ones(len(pos))]
    return np.einsum('vk,vkij,vj->vi',ws,mats[indices,:,:],xyz1)[:,:3]


bind=matrices({})
bind_error=max(np.max(abs(deform(pos,idx,ws,bind)-pos)) for pos,idx,ws,e,l in body)
assert bind_error<1e-5
animation_report={}
for name in ('idle','walk','run','sit_ground'):
    anim=next(a for a in library['animations'] if a['name']==name)
    tracks=[]
    for c in anim['channels']:
        target=c['target']
        sampler=anim['samplers'][c['sampler']]
        t=read(library,library_buf,sampler['input']).ravel()
        v=read(library,library_buf,sampler['output'])
        tracks.append((library['nodes'][target['node']]['name'],target['path'],t,v))
    samples=[]
    for fraction in (0,.25,.5,.75):
        pose={}
        for bone,path,t,v in tracks:
            time=t[0]+fraction*(t[-1]-t[0])
            if len(t)==1:value=v[0]
            elif path=='rotation':value=slerp(t,v,time)
            else:value=[np.interp(time,t,col) for col in v.T]
            pose[(bone,path)]=value
        mats=matrices(pose)
        ratios=[]
        for pos,idx,ws,edges,length in body:
            moved=deform(pos,idx,ws,mats)
            ratios.extend(np.linalg.norm(moved[edges[:,0]]-moved[edges[:,1]],axis=1)/length)
        samples.append(dict(phase=fraction,edge_length_ratio_p01_p99=np.percentile(ratios,[1,99]).round(3).tolist(),
                            edge_length_ratio_extremes=np.round([min(ratios),max(ratios)],3).tolist()))
    animation_report[name]=samples
def embedded(im):
    view=doc['bufferViews'][im['bufferView']]
    start=view['byteOffset']
    return Image.open(io.BytesIO(buf[start:start+view['byteLength']])).size
print(json.dumps(dict(triangles=sum(doc['accessors'][p['indices']]['count']//3 for p in primitives),
    body_triangles=sum(doc['accessors'][p['indices']]['count']//3 for p in primitives
                       if doc['materials'][p['material']]['name'] in ('Undershirt','Shorts and socks','Rib knit','Exposed skin','Nail bed')),
    drawn_materials=len({p['material'] for p in primitives}),material_records=len(doc['materials']),
    joints=len(joints),shared_clips=len(library['animations']),shared_target_names=len(shared_targets),
    missing_targets=missing,shared_sha256=hashlib.sha256(shared.read_bytes()).hexdigest(),
    embedded_clips=[a['name'] for a in doc['animations']],bind_max_error_m=bind_error,
    maps={**{im['name']:embedded(im) for im in doc['images']},
          **{p.name:Image.open(p).size for p in file.parent.glob(file.stem+'.*.png')}},
    body_deformation=animation_report),indent=2))
