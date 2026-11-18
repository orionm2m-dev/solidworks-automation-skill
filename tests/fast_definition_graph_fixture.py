"""Portable synthetic inventory graph shared by offline capture parity tests."""
class Node:
    def __init__(self,role,native_id=0,rows=None,interface=''):
        self.role,self.native_id,self.rows,self.interface=role,native_id,rows,interface

class Graph:
    def __init__(self,generated=False,change=None):
        self.app=Node('app');self.doc=Node('doc');self.machine=Node('machine')
        self.setup=Node('feature_setup',201);self.feature=Node('feature',202)
        self.opsetup=Node('operation_setup',301);self.ops=[Node('operation',401),Node('operation',402)]
        self.tools=[Node('tool',501),Node('tool',502)];self.generated=generated;self.change=change
        self.trace=[];self.calls=0
        if change=='cross_kind_id':self.tools[0].native_id=202
        if change=='duplicate_operation':self.ops[1].native_id=401
    def typed(self,obj,name):
        self.trace.append(('qi',obj.role,name))
        return Node(obj.role,obj.native_id,obj.rows,name)
    def read(self,obj,name,*args):
        self.calls+=1;self.trace.append(('read',obj.role,name,tuple(x.native_id if isinstance(x,Node)else x for x in args)))
        if self.change=='getter_failure' and name=='GetIsToolpathGenerated':raise RuntimeError('injected')
        i=0 if obj.native_id in(401,501)else 1
        if name=='IGetActiveDoc':return self.doc
        if name=='IGetMachine':return self.machine
        if name=='GetDocType':return 3 if self.change=='wrong_document'else 1
        if name=='GetActiveConfigurationName':return 'configuration'
        if name=='GetActiveConfiguration':return Node('configuration')
        if name=='SWConfigurationName':return 'Default'
        if name=='ConfigurationName':return 'other'if self.change=='wrong_configuration'else 'configuration'
        if name=='MachType':return 3 if self.change=='wrong_machine'else 1
        if name=='IGetEnumSetups':return Node('collection',rows=[self.setup])
        if name=='IGetEnumFeatures':return Node('collection',rows=[self.feature])
        if name=='IGetEnumOpSetups':return Node('collection',rows=[self.opsetup])
        if name=='IGetEnumOperations':return Node('collection',rows=self.ops)
        if name=='Count':return True if self.change=='bool_count'else len(obj.rows)
        if name=='Item':return obj.rows[args[0]]
        if name=='GetCWObjectID':return args[0].native_id,True
        if name=='Axis':return [0,0,-1]
        if name=='GetReferencePosition':return [0,0,0]
        if name=='Suppressed':return False
        if name=='FeatureName':return 'Pocket'
        if name in('VolumeType','SubType'):return 2
        if name=='OpernType':return i if obj.interface=='ICWMillOperation'else 0
        if name=='GetIsToolpathGenerated':return bool(self.generated and i==0)
        if name=='IGetAllFeatures':return Node('collection',rows=[self.feature]* (2 if self.change=='duplicate_links'else 1))
        if name=='IGetEnumToolpaths':return Node('collection',rows=[Node('path')] if self.generated and i==0 else [])
        if name=='RecordCount':return True if self.change=='bool_record_count'else 17
        if name=='IGetTool':return self.tools[i]
        if name=='IsMillTool':return True
        if name=='ToolType':return 1
        if name=='CutDiameter':return 8.0 if i==0 else 20.0
        if name=='Protrusion':return 25.0 if i==0 else 60.0
        raise AssertionError((obj.role,name))
