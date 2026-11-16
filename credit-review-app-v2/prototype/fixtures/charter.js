export const evidence = [
  {
    "id": "e1",
    "title": "股权出质事前告知",
    "page": 14,
    "bbox": [
      105,
      107,
      1047,
      276
    ],
    "text": "股东以本行股权出质为自己或他人担保的，应当严格遵守法律法规和监管部门要求，并事前书面告知本行董事会。董事会办公室或董事会指定的其他部门，负责承担股权质押信息的收集、整理和报送等日常工作。"
  },
  {
    "id": "e2",
    "title": "担保事项批准权",
    "page": 15,
    "bbox": [
      180,
      460,
      829,
      498
    ],
    "text": "（十二）审议批准第四十七条规定的担保事项；"
  },
  {
    "id": "e3",
    "title": "对外担保例外",
    "page": 15,
    "bbox": [
      123,
      1228,
      1057,
      1303
    ],
    "text": "第四十七条 本行下列对外担保行为，须经股东大会审议通过（银行正常经营范围内的业务除外）。"
  },
  {
    "id": "e4",
    "title": "担保规模限制",
    "page": 15,
    "bbox": [
      108,
      1304,
      1054,
      1380
    ],
    "text": "（一）本行及本行控股子公司（子银行）的对外担保总额，达到或超过最近一期经审计净资产的50%以后提供的任何担保；"
  }
];

// 样本中未找到对应原文的检查项（合成项）。
export const notFound = {
  id: "not-found",
  title: "独立担保授权书",
  page: 0,
  bbox: null,
  text: "本次样本未找到相关原文。"
};

export const pages = [14, 15];

// PDF 页面坐标系尺寸（px），用于坐标线框换算。
export const pageSize = { width: 1191, height: 1684 };

export const task = {
  // 合成占位任务名：评审用，不指向任何真实客户。
  name: "示例对公客户 · 流动资金贷款",
  customerRole: "借款人",
  revision: "输入版本 v1",
};

export const otherMaterials = {
  license: "营业执照",
  financial: "审计财报",
};

// 评审场景元数据。status 决定顶部状态徽章，affected 为受影响的检查项 id。
export const scenarios = {
  normal: {
    label: "正常核对",
    status: "ready",
    banner: "请逐条核对摘录和未找到结果。",
    affected: [],
  },
  processing: {
    label: "处理中",
    status: "processing",
    banner: "章程处理中，检索摘录仍在进行，结果尚未就绪。",
    affected: [],
    processing: {
      stages: [
        { name: "OCR 完成", state: "done" },
        { name: "文本分窗", state: "done" },
        { name: "检索摘录", state: "running" },
      ],
      hint: "正在检索条款摘录，完成后可逐条核对。",
    },
  },
  missing: {
    label: "缺材料",
    status: "missing",
    banner: "本轮核对所需的「公司章程」尚未上传。",
    affected: [],
    missingMaterial: {
      material: "公司章程",
      hint: "上传入口在阶段 B 接入",
    },
    completionRule: "待决策（待产品确认：是否允许在缺材料状态下完成核对）",
  },
  invalid: {
    label: "覆盖不全 · 无效出处",
    status: "warn",
    banner: "识别覆盖不完整，暂不能完成核对。",
    affected: ["e4"],
    affectedLabel: "受影响 · 无效出处",
    affectedReason: "无效出处",
    affectedHint: "该条款引用了不存在的出处块 ID，无法在原件中核验；「查看出处」仅能定位到最后已知坐标。",
  },
  truncated: {
    label: "覆盖不全 · 输出截断",
    status: "warn",
    banner: "识别覆盖不完整，暂不能完成核对。",
    affected: ["e2", "e3"],
    affectedLabel: "受影响 · 输出截断",
    affectedReason: "输出截断",
    affectedHint: "模型输出在此处被截断，该条款摘录可能不完整，需重新出稿后确认。",
  },
  complete: {
    label: "已完成只读",
    status: "done",
    banner: "核对已完成，可以查看历史决定与拒绝原因。",
    affected: [],
  },
};

export const statusText = {
  ready: "正常核对",
  processing: "处理中",
  missing: "缺材料",
  warn: "覆盖不全",
  done: "已完成",
};

// 已完成只读场景的兜底历史决定（当本地没有存储记录时使用）。
export const completedFallbackDecisions = {
  e1: { value: "接受" },
  e2: { value: "接受" },
  e3: { value: "拒绝", reason: "样本第 15 页未见对应条款，需人工确认。" },
  e4: { value: "接受" },
};
