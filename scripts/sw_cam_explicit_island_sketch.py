"""Four explicit LINE/ARC island sketches using the existing signed native builder.
This is a component, not a CAM endpoint or authority loader. The enclosing action
owns the session lifetime, immutable pins, CAM invariants, durable once journal,
cleanup and terminal receipt. No feature, island, GOP/GTP, Save or retry here.
"""
from copy import deepcopy
import math
from types import SimpleNamespace
from scripts import sw_cam_profile_sketch as core
from scripts import sw_cam_signed_mixed_profile as mixed
from scripts import sw_cam_signed_mixed_profile_sketch as sketch

SCOPE='FOUR_EXPLICIT_CLOSED_ISLAND_SKETCH_COMPONENT_V1'


def require(ok,message):
    if not ok:raise ValueError(message)


def compile_loops(loops,*,plane_z_mm,sketch_names,plane_names):
    """Consume exact serialized footprints; never offset, scale or polygonize."""
    z=mixed.number(plane_z_mm)
    require(type(loops)is list and len(loops)==4,'Exactly four serialized footprints required')
    require(type(sketch_names)is list and type(plane_names)is list and len(sketch_names)==len(plane_names)==4,'Four explicit sketch and plane names required')
    names=[core._name(n)for n in sketch_names+plane_names]
    require(len({n.casefold()for n in names})==8,'Distinct explicit names required')
    angles=[];specs=[]
    for loop,sn,pn in zip(loops,sketch_names,plane_names):
        require(type(loop)is dict and set(loop)=={'angle_deg','edges'},'Exact footprint fields required')
        angle=mixed.number(loop['angle_deg']);require(0<=angle<360,'Bounded declared angle required');angles.append(angle)
        edges=loop['edges'];require(type(edges)is list and len(edges)==4,'Exactly four edges required')
        rows=[]
        for edge in edges:
            require(type(edge)is dict and edge.get('kind')in('Line','Circle'),'Only explicit LINE/ARC footprint edges')
            keys={'kind','start','end'}|({'centre','radius_mm','ccw'}if edge['kind']=='Circle'else set())
            require(set(edge)==keys,'Exact footprint edge fields required')
            a,b=mixed.vector(edge['start']),mixed.vector(edge['end'])
            require(all(abs(p[2]-z)<=1e-9 for p in (a,b)),'Requested plane must match serialized coordinates; no relocation')
            row=dict(kind='line'if edge['kind']=='Line'else'arc',start_model_mm=a,end_model_mm=b)
            if row['kind']=='arc':
                c=mixed.vector(edge['centre']);r=mixed.number(edge['radius_mm'])
                require(type(edge['ccw'])is bool and abs(c[2]-z)<=1e-9,'Explicit signed arc direction and plane required')
                theta=math.atan2(b[1]-c[1],b[0]-c[0])-math.atan2(a[1]-c[1],a[0]-c[0])
                sweep=theta%mixed.TAU if edge['ccw'] else -((-theta)%mixed.TAU)
                require(1e-6<abs(sweep)<math.pi,'Only unambiguous minor footprint arcs admitted')
                row.update(center_model_mm=c,radius_mm=r,sweep_radians=sweep)
            row['mid_model_mm']=mixed.at(row,.5);rows.append(row)
        arcs=[v for v in rows if v['kind']=='arc']
        require(len(arcs)==2 and math.dist(arcs[0]['center_model_mm'],arcs[1]['center_model_mm'])<=1e-9,'Two concentric arcs and two straight sides required')
        require(arcs[0]['sweep_radians']*arcs[1]['sweep_radians']<0 and abs(arcs[0]['radius_mm']-arcs[1]['radius_mm'])>1e-5,'Distinct inner/outer arcs must have opposite directions')
        specs.append(sketch._input(dict(plane_axis='Z',plane_offset_mm=z,sketch_name=sn,plane_name=pn,profile=dict(kind='closed_mixed',segments=rows))))
    require(len(set(angles))==4,'Four distinct footprint angles required')
    return specs


def verify_readback(spec,observed):
    spec=sketch._input(spec)
    require(len(spec['profile']['segments'])==4 and sum(x['kind']=='arc'for x in spec['profile']['segments'])==2,'One two-arc/two-line footprint required')
    require(observed.get('arc_interval_midpoint_verified')is True and observed.get('native_rotation_direction_qualified')is True,'Qualified signed native arc readback required')
    require(observed.get('native_rotation_direction_assumed')is False and observed.get('underlying_curve_trim_used')is False,'Do not infer arcs from untrimmed underlying curve')
    require(observed.get('readback_tolerance_m')==core.TOL_M,'Existing native readback tolerance required')
    core._rigid_transform(SimpleNamespace(ArrayData=observed['model_to_sketch_transform']))
    rows=observed['entities'];mapping=mixed.match_rows(spec['profile']['segments'],rows,core.TOL_M)
    require(mapping==observed['expected_segment_to_native_index'],'Native entity mapping differs')
    for row in rows:
        if row['type']=='arc':
            trim=row.get('native_trim',{})
            require(trim.get('independent_native_length_verified')is True and trim.get('underlying_curve_trim_used')is False,'Native arc length must independently confirm the interval')
    return dict(closed_mixed_profile_verified=True,entity_count=len(rows),segment_mapping=mapping,model_coordinate_geometry_verified=True,CAM_island_association_verified=False,machining_qualified=False)


def verify_cad_delta(before,after,created):
    names=[r['name']for r in created]
    require(len(names)==len(set(names)),'Duplicate created CAD feature')
    require([r for r in after['features']if r['name']not in names]==before['features'],'Existing CAD tree changed')
    require([r for r in after['features']if r['name']in names]==created,'Unexpected new CAD feature')
    require(core._same_bodies(before['solids'],after['solids']),'Solid body invariants changed')
    require(all(before[k]==after[k]for k in ('pid','path','saved_file_sha256','spec')),'Document/source/spec changed')
    old=[p for p in after['planes']if p['name']not in names]
    require(old==before['planes'],'Existing reference plane changed')
    require(after['needs_save']is True,'Unsaved native sketch change not observed')


def create_one(sw,*,process_id,document_path,source_sha256,expected_needs_save,spec,check,claim,persist,report):
    """One native sketch; caller check must guard lifetime/runtime/events/CAM.
    claim() must durably consume the caller's target+action intent before return.
    Failed/uncertain calls must not be replayed. Read/adopt uses a separate action.
    """
    require(type(process_id)is int and process_id>0 and type(expected_needs_save)is bool,'Strict caller identity and dirty-state binding required')
    require(type(report)is dict and not report,'Fresh per-sketch report required')
    spec=sketch._input(spec)
    require(len(spec['profile']['segments'])==4 and sum(x['kind']=='arc'for x in spec['profile']['segments'])==2,'One two-arc/two-line footprint required')
    report.update(scope=SCOPE,status='error',mutation_attempted=False,native_readback_verified=False,automatic_retry=False,Save_attempted=False,CAM_feature_creation_attempted=False,AddIsland_attempted=False,GOP_attempted=False,GTP_attempted=False)
    def boundary():
        check();core._identity(sw,process_id,document_path)
        require(core._sha(document_path)==source_sha256,'Saved source changed during sketch-only component')
    try:
        boundary();before,model,refs=core._snapshot(sw,process_id,document_path,spec);report['before']=before;persist()
        require(before['saved_file_sha256']==source_sha256 and before['needs_save']is expected_needs_save,'Current document state differs from caller baseline')
        names={r['name'].casefold()for r in before['features']}
        require(spec['sketch_name'].casefold()not in names and spec['plane_name'].casefold()not in names,'New names already exist; do not replay')
        core._select_plane(before);boundary();claim()
        report['mutation_attempted']=True;persist()
        created=sketch._create(sw,model,before,refs,boundary,report)
        boundary();after,_,_=core._snapshot(sw,process_id,document_path,spec);report['after']=after;persist()
        expected=[dict(name=n,type='ProfileFeature'if n==spec['sketch_name']else'RefPlane')for n in created]
        verify_cad_delta(before,after,expected)
        require(report.get('sketch_edit_exited')is True,'Owned sketch edit must be closed')
        report['geometry_proof']=verify_readback(spec,report['sketch_readback']);boundary()
        report.update(status='sketch_observed',native_readback_verified=True,created_features=expected)
        return report
    except Exception:
        report.update(status='uncertain'if report['mutation_attempted']else'error',native_readback_verified=False)
        raise
    finally:
        try:persist()
        except Exception:
            report.update(status='uncertain'if report['mutation_attempted']else'error',native_readback_verified=False,receipt_write_failed=True)
            raise
