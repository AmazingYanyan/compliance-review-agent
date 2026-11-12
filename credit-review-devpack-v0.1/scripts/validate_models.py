#!/usr/bin/env python3
"""Pydantic-v2 validation of generated schema/DTO/fixture consistency."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract_models as models
from pydantic import TypeAdapter, ValidationError

ROOT = HERE.parent
def read(path):
    return json.loads((ROOT / path).read_text())

standalone = {
    'classification.output.schema.json': models.ClassificationOutput,
    'text_search.output.schema.json': models.TextSearchOutput,
    'vision_match.output.schema.json': models.VisionMatchOutput,
    'checklist.schema.json': models.Checklist,
    'normalized_page.schema.json': models.NormalizedPage,
}
for name, cls in standalone.items():
    saved = read('contracts/' + name)
    saved.pop('$schema', None)
    saved.pop('$id', None)
    assert saved == cls.model_json_schema(), f'Schema drift: {name}'

oas = read('contracts/openapi.json')
for name, saved in oas['components']['schemas'].items():
    cls = getattr(models, name)
    current = cls.model_json_schema(ref_template='#/components/schemas/{model}')
    current.pop('$defs', None)
    assert saved == current, f'OpenAPI DTO drift: {name}'

fixtures = {
    'classification.example.json': models.ClassificationOutput,
    'text_search.example.json': models.TextSearchOutput,
    'vision_match.example.json': models.VisionMatchOutput,
    'normalized_page.example.json': models.NormalizedPage,
    'review_results.example.json': models.ResultPage,
}
for name, cls in fixtures.items():
    cls.model_validate_json((ROOT/'fixtures'/name).read_text())
TypeAdapter(list[models.ResultView]).validate_python(read('fixtures/result_variants.example.json'))
models.Checklist.model_validate(read('contracts/checklist.borrower.v1.json'))
TypeAdapter(list[models.RoleCapability]).validate_python(read('contracts/feature_flags.json')['roles'])
for case in read('fixtures/statistics_cases.json'):
    models.Statistics.model_validate(case['expected'])

classification=read('fixtures/classification.example.json')
vision=read('fixtures/vision_match.example.json')
page=read('fixtures/normalized_page.example.json')
bad_vision={**vision,'matches':[{'crop_id':'not-a-uuid','recognized_text':None,'relation_status':'matched','relevance_reason':'invalid'}]}
bad_cases=[
    (models.ClassificationOutput,{**classification,'unexpected':True}),
    (models.ClassificationOutput,{**classification,'confidence':1.5}),
    (models.ClassificationOutput,{**classification,'material_type':'financial_analysis'}),
    (models.VisionMatchOutput,bad_vision),
    (models.NormalizedPage,{**page,'width_px':0}),
    (models.SourceRef,{'block_id':page['blocks'][0]['block_id'],'start_char':-1,'end_char':2}),
    (models.DecisionWrite,{'run_id':page['task_id'],'decision':'rejected','reject_reason':'x'*4001}),
]
for cls,payload in bad_cases:
    try:
        cls.model_validate(payload)
    except ValidationError:
        pass
    else:
        raise AssertionError(f'Invalid payload accepted by {cls.__name__}')
print(json.dumps({'standalone_schema_models':len(standalone),'openapi_dtos':len(oas['components']['schemas']),'primary_fixtures':len(fixtures),'negative_cases':len(bad_cases),'errors':[],'external_services_tested':False},ensure_ascii=False,indent=2))
