"""Fit the existing rear locks on the approved scalp and expose the plait root."""
# Stations are side distance / half-cheek and height above chin / head height.
# Width is a multiple of half-cheek. Side layers cross at different heights.
# The first pair stays at the temples to preserve the front opening.
layers = {
    2: [(1.40,.77,.12),(1.55,.65,.22),(1.42,.48,.26),(.94,.37,.23),(.41,.25,.13),(.06,.18,.025)],
    3: [(1.25,.91,.05),(1.52,.75,.22),(1.40,.65,.34),(.90,.52,.36),(.47,.42,.29),(.04,.32,.02)],
    4: [( .93,.92,.06),(1.25,.83,.28),(1.18,.73,.39),(.86,.64,.34),(.53,.60,.28),(.02,.48,.030)],
    5: [( .79,.92,.03),(.99,.85,.10),(1.14,.79,.16),(1.02,.72,.16),(.80,.68,.12),(.59,.64,.012)],
    6: [( .16,.96,.05),(.41,.93,.30),(.60,.87,.45),(.56,.79,.44),(.39,.72,.36),(.03,.60,.022)],
}
cheek_radius = .11788663 / 2
head_height = .23221159
chin_z = 1.42720544
part_asymmetry = .065
side_tuck = (.035, -.018)
def ease(a,b,x):
    t=np.clip((x-a)/(b-a),0.,1.)
    return float(t*t*(3-2*t))
def station(rows,t):
    # Catmull–Rom interpolation avoids corners between the handful of guides.
    q=t*(len(rows)-1); j=min(int(q),len(rows)-2); u=q-j
    a,b,c,d=[np.array(rows[int(np.clip(k,0,len(rows)-1))]) for k in (j-1,j,j+1,j+2)]
    return .5*(2*b+(-a+c)*u+(2*a-5*b+4*c-d)*u*u+(-a+3*b-3*c+d)*u**3)
support_index=next(i for i,s in enumerate(layout['islands']) if s['kind']=='support')
support=BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],
                             [tuple(p.vertices) for p,tile in zip(mesh.polygons,poly_tiles) if tile==support_index])
def back_y(x,z):
    surface= support.ray_cast(Vector((x,.22,z)),Vector((0,-1,0)),.28)[0]
    if surface is not None:return surface.y
    return .01+.097*math.sqrt(max(.01,1-(x/.096)**2-((z-1.552)/.110)**2))
normals=[n.vector.copy() for n in mesh.corner_normals]
new_normals={}
base_pos={i:mesh.vertices[i].co.copy() for ids in groups for i in ids}
for spec,ids in zip(layout['islands'],groups):
    if spec['kind']!='combed' or abs(spec['seed'])==1:continue
    side=1 if spec['seed']>0 else -1
    g=abs(spec['seed']); path=[]; widths=[]
    for j in range(25):
        t=j/24
        x,h,width=station(layers[g],t)
        # Offset the paired centre part and stagger its entries into the plait.
        x=side*x*cheek_radius + part_asymmetry*cheek_radius*math.sin(t*math.pi+g*.8)
        z=chin_z+head_height*(h+side_tuck[1 if side > 0 else 0]*.23*math.sin(math.pi*t+g*.47))
        y=back_y(x,z)+(.004+.0012*(g%3))*math.sin(math.pi*t)+.001
        path.append(Vector((x,y,z))); widths.append(max(.00035,width*cheek_radius))
    for j,pos in enumerate(path):
        t=j/24
        tangent=(path[min(24,j+1)]-path[max(0,j-1)]).normalized()
        radial=Vector((pos.x/.105,max(.16,pos.y/.103),max(-.3,(pos.z-1.542)/.105))).normalized()
        cross=tangent.cross(radial).normalized()
        outward=cross.cross(tangent).normalized()
        # Keep the root as it rounds the forward scalp into the rear field.
        blend=ease(.08,.45,t) if g==2 else ease(.0,.25,t) if g==3 else 1.
        for k in range(12):
            a=k*math.tau/12;s,c=math.sin(a),math.cos(a);idx=ids[12*j+k]
            width=widths[j]
            p=pos+cross*(width*s)+outward*(width*(.42*c if c>0 else .16*c))
            mesh.vertices[idx].co=base_pos[idx].lerp(p,blend)
            # Broad faces carry one band. Only the rolled margins turn into
            # shadow. Closely paired short leaves share their parent's plane.
            upper=Vector((0,0,.31+.36*(g in (4,6))))
            normal=(radial+upper).normalized()*c+cross*(s*(.74 if g in (4,6) else .94))
            new_normals[idx]=(normal.normalized(),blend)

# Run the upper braid down the back surface. At a crossing the strand
# travelling inward sits above its partner, producing the drawn descending V.
# Round cross sections follow the moving tangent, including at the shoulder.
root_z = 1.545
end_z = 1.157
pitch_turns = 2.90
upper_orbit = .0185
strand_width = .0125
strand_depth = .0078
strand_id = 0
for spec,ids in zip(layout['islands'],groups):
    if spec['kind']!='braid': continue
    centres=[]; phases=[]
    for j in range(57):
        t=j/56; phase=math.tau*(pitch_turns*t+strand_id/3+.04)
        z=root_z+(end_z-root_z)*t
        orbit=upper_orbit*(1-.58*t)
        # The gathered start is behind the crown and narrows at the tie.
        axis=station([(.094,),(.103,),(.098,),(.105,),(.118,),(.122,),(.118,)],t)[0]
        depth=.0068*(1-.58*t)
        pos=Vector((orbit*math.sin(phase),axis-depth*math.sin(2*phase),z))
        centres.append(pos);phases.append(phase)
    for j,pos in enumerate(centres):
        t=j/56
        tangent=(centres[min(56,j+1)]-centres[max(0,j-1)]).normalized()
        rear=Vector((0,1,0))
        side_axis=tangent.cross(rear).normalized()
        rear_axis=side_axis.cross(tangent).normalized()
        taper=(1-.63*t)*(.60+.40*ease(0,.14,t))
        w=strand_width*taper*(1+.18*abs(math.sin(phases[j])))
        dep=strand_depth*taper
        carry=1-ease(.57,.94,t)
        for k in range(10):
            i=ids[j*10+k];a=k*math.tau/10
            cs,sn=-math.cos(a),math.sin(a)
            p=pos+rear_axis*(dep*cs)+side_axis*(w*sn)
            mesh.vertices[i].co=base_pos[i].lerp(p,carry)
            # Upper ridges catch daylight; limit the bright arc to the rounded
            # face of each strand, so the crossing stays visible in shadow.
            n=(rear_axis*cs+side_axis*(sn*.79)+Vector((0,0,.52+.32*cs))).normalized()
            new_normals[i]=(n,carry)
    strand_id+=1
for loop in mesh.loops:
    if loop.vertex_index in new_normals:
        n,w=new_normals[loop.vertex_index]
        normals[loop.index]=normals[loop.index].lerp(n,w).normalized()
mesh.normals_split_custom_set([tuple(n) for n in normals])
mesh.update()
# Change only authored rear islands in the guide. Use the official distance
# field writer on the combined original and revised guides; retain palette.
subprocess.run(['python3',str(SESSION/'back-hair/strokes.py'),str(PREVIOUS/'hair/final'),
                str(ROOT)],check=True)
subprocess.run(['python3',str(repo/'living/tools/characters/ink_field.py'),
                str(ROOT/'lock-lines.png'),str(ROOT/'own-cora-live.hair.png'),
                '--range','.009'],check=True)
shade = [44,8,2]
hair_material['slop']['hair']['shade'] = shade
target_path = ROOT/'own-cora-live.calibration.json'
targets = json.loads(target_path.read_text())
targets['calibrated_base_srgb']['shade'] = shade
target_path.write_text(json.dumps(targets, indent=2)+'\n')
export_current()
