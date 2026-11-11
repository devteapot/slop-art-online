"""Load a glb's triangles by material filter, in world space (bind pose), and the bones' world positions."""
import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import G
def load(path, want):
    g = G(path); W, par = g.world()
    tris = []; norms = []; uvs = []
    for ni, n in enumerate(g.nodes):
        if 'mesh' not in n: continue
        m = g.j['meshes'][n['mesh']]
        for p in m['primitives']:
            mat = g.j['materials'][p['material']]['name']
            if not want(mat): continue
            P = g.acc(p['attributes']['POSITION']).astype(float); Nn = g.acc(p['attributes']['NORMAL']).astype(float)
            M = W[ni]; P = P @ M[:3,:3].T + M[:3,3]; Nn = Nn @ M[:3,:3].T
            I = g.acc(p['indices']).reshape(-1,3)
            tris.append((P, Nn, I, mat, g.acc(p['attributes']['TEXCOORD_0'])))
    bones = {n.get('name'): W[i][:3,3] for i, n in enumerate(g.nodes)}
    return tris, bones, g
def soup(tris):
    """concatenate into one vertex array with offsets"""
    Ps=[];Ns=[];Is=[];o=0
    for P,N,I,mat,uv in tris:
        Ps.append(P);Ns.append(N);Is.append(I+o);o+=len(P)
    return np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Is)
def section(P, I, axis, value):
    """segments where plane coord[axis]==value cuts triangles -> list of (a,b) points"""
    d = P[:,axis]-value; segs=[]
    T = I
    s = np.sign(d[T]); 
    cross = ~((s>0).all(1) | (s<0).all(1))
    for t in T[cross]:
        pts=[]
        for a,b in ((t[0],t[1]),(t[1],t[2]),(t[2],t[0])):
            if (d[a]>0)!=(d[b]>0):
                u = d[a]/(d[a]-d[b]); pts.append(P[a]+(P[b]-P[a])*u)
        if len(pts)==2: segs.append(pts)
    return np.array(segs)
