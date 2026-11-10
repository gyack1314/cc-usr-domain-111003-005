def patch(base,changes):
    result=dict(base)
    for key,value in changes.items():
        if key not in result:raise ValueError('条款不存在：'+key)
        result[key]=value
    return result
def differences(before,after):
    return {k:{'before':before.get(k),'after':after.get(k)} for k in sorted(set(before)|set(after)) if before.get(k)!=after.get(k)}
def referenced_targets(documents):
    return sorted({k for d in documents for k in d.get('replaces',{})})
TOOLS={'patch':patch,'differences':differences,'referenced_targets':referenced_targets}
