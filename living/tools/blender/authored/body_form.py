"""Add the fitting body under the clothed export. Run on the head master in Blender.
The sleeve and boot openings cover the cut ends. Hidden surfaces are removed at export.
"""
from math import exp
from pathlib import Path
import sys

import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import person as p

path=Path(sys.argv[-1]).resolve()
bpy.ops.wm.open_mainfile(filepath=str(path))
arm=next(o for o in bpy.data.objects if o.type=="ARMATURE")
params=p.person_params.draw(p.person_params.from_variant("type:adult-f-a"))
spec=p.person_params.resolve(params)
p.configure(spec)
p.FAR=False
waist=p.upper_garment(p.Part("Fitting torso"),0.,[.94,1.01,1.08,1.16,1.24,1.32],
                      hem=[],cuff=(-.705,[]),collar=[(.028,-.006,{"J_Bip_C_Neck":1.})]).mirrored()
legs=p.trousers(p.Part("Fitting legs"),0.,top=1.01,bottom=.09).mirrored()
for cage in (waist,legs):
    ob=p.build(cage,arm,p.MAT["skin"],lambda *args:p.SKIN)
    for v in ob.data.vertices:
        x,y,z=v.co
        # Deltoid cap, taper into wrist, patellar plane and gastrocnemius.
        shoulder=exp(-((abs(x)-.226)/.067)**2-((z-1.43)/.077)**2)
        knee=exp(-((z-.55)/.045)**2)
        calf=exp(-((z-.36)/.094)**2)
        v.co.z+=.009*shoulder
        v.co.y+=.008*shoulder+.006*knee-.007*calf
    ob.shape_key_add(name="Basis")
    build=ob.shape_key_add(name="Athletic build",from_mix=False)
    for v in build.data:
        x,y,z=v.co
        gain=exp(-((z-1.32)/.15)**2)+.6*exp(-((z-.79)/.15)**2)
        v.co.x+=.05*x*gain
        v.co.y+=.11*y*gain
    ob["atelier_fitting_surface"]=True
    ob.hide_set(True)
    ob.hide_render=True
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(path),compress=True)
