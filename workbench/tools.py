import argparse,json,sys
from pathlib import Path
from .domain import TOOLS
from .evidence import Journal,manifest,verify,atomic_json

def main():
    parser=argparse.ArgumentParser(description='资料与领域计算工具')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    p=sub.add_parser('call');p.add_argument('tool',choices=sorted(TOOLS));p.add_argument('input',type=Path)
    p=sub.add_parser('manifest');p.add_argument('root',type=Path);p.add_argument('output',type=Path)
    p=sub.add_parser('verify');p.add_argument('root',type=Path);p.add_argument('manifest',type=Path)
    p=sub.add_parser('note');p.add_argument('database',type=Path);p.add_argument('key');p.add_argument('input',type=Path)
    p=sub.add_parser('notes');p.add_argument('database',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='list':result={'tools':sorted(TOOLS)}
        elif args.command=='call':
            payload=json.loads(args.input.read_text(encoding='utf-8'))
            if not isinstance(payload,dict):raise ValueError('参数文件必须是对象')
            result=TOOLS[args.tool](**payload)
        elif args.command=='manifest':
            if args.output.resolve().is_relative_to(args.root.resolve()):raise ValueError('清单应放在材料目录外')
            result=manifest(args.root);atomic_json(args.output,result)
        elif args.command=='verify':
            result=verify(args.root,json.loads(args.manifest.read_text(encoding='utf-8')))
            if result:print(json.dumps({'mismatch':result},ensure_ascii=False));return 2
        elif args.command=='note':result={'sequence':Journal(args.database).append(args.key,json.loads(args.input.read_text(encoding='utf-8')))}
        else:result=Journal(args.database).read()
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(str(exc),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
