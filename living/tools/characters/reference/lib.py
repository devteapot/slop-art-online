import json, struct, numpy as np
CT = {5120:np.int8,5121:np.uint8,5122:np.int16,5123:np.uint16,5125:np.uint32,5126:np.float32}
NC = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
class G:
    def __init__(self, path):
        b = open(path,'rb').read(); off = 12; ch = []
        while off < len(b):
            l, t = struct.unpack('<I4s', b[off:off+8]); ch.append(b[off+8:off+8+l]); off += 8+l
        self.j = json.loads(ch[0]); self.B = ch[1]
        self.nodes = self.j['nodes']
    def acc(self, i):
        a = self.j['accessors'][i]; bv = self.j['bufferViews'][a['bufferView']]
        n = NC[a['type']]; dt = np.dtype(CT[a['componentType']])
        off = bv.get('byteOffset',0)+a.get('byteOffset',0); stride = bv.get('byteStride', dt.itemsize*n)
        raw = np.frombuffer(self.B, dtype=np.uint8, count=stride*(a['count']-1)+dt.itemsize*n, offset=off)
        out = np.lib.stride_tricks.as_strided(raw, shape=(a['count'], dt.itemsize*n), strides=(stride,1)).copy().view(dt).reshape(a['count'], n)
        if a.get('normalized') and dt.kind in 'iu': out = out.astype(np.float32)/np.iinfo(dt).max
        return out
    def image(self, i):
        im = self.j['images'][i]; bv = self.j['bufferViews'][im['bufferView']]
        o = bv.get('byteOffset',0); return self.B[o:o+bv['byteLength']]
    def mesh(self, name):
        for mi, m in enumerate(self.j['meshes']):
            if m['name'].startswith(name): return mi, m
    def world(self):
        # node world matrices
        par = {}
        for i,n in enumerate(self.nodes):
            for c in n.get('children',[]): par[c] = i
        def local(n):
            if 'matrix' in n: return np.array(n['matrix']).reshape(4,4).T
            t = np.array(n.get('translation',[0,0,0])); r = n.get('rotation',[0,0,0,1]); s = np.array(n.get('scale',[1,1,1]))
            x,y,z,w = r
            R = np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
            M = np.eye(4); M[:3,:3] = R*s; M[:3,3] = t; return M
        W = {}
        def w(i):
            if i in W: return W[i]
            M = local(self.nodes[i]); W[i] = (w(par[i]) @ M) if i in par else M; return W[i]
        return [w(i) for i in range(len(self.nodes))], par
