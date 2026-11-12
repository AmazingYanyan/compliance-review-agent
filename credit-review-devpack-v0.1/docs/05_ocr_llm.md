# OCR、图片与LLM实现规范

## 1. 输入来源及已经核实的事实

当前唯一OCR服务目标：用户提供的公网异步接口 `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`，模型 `PaddleOCR-VL-1.6`。请求头示例是`Authorization: bearer <TOKEN>`，凭据从.env读取。本包未调用该服务，未验证账号配额。

用户提供的12页法律尽调JSON和1页营业执照JSON都是“每页对象组成的数组”快照；异步下载协议的原始JSONL外层则是每行`result.layoutParsingResults[]`。不能把数组快照直接当作HTTP响应契约。本包含两份保留结构、去除签名URL的样本。

营业执照样本包含20个parsing块、23个layout检测框。可核实印章块：label=seal、block_id=15、block_order=13、group_id=15、bbox=[608,398,721,519]；block_content是HTML，含相对图片路径`imgs/img_in_seal_box_608_398_721_519.jpg`及“北京市朝阳区市场监督管理局”“110505098”。对应图片在markdown.images中以同路径为键，值为远程URL。该样本同时有国徽header_image和一个image块，不能把全部图片都识别为印章。

这证明了样本中的印章文字、坐标与图片引用路径；不证明所有样本都能识别，不证明签名有独立label，也不证明印章真伪。该营业执照印章只用于适配器测试，不给借款人营业执照清单擅自新增印章检查项。当前财报才有审计单位印章、注册会计师签名检查项。

## 2. 客户端复用与REST契约

已有官方PaddleOCRClient/AsyncPaddleOCRClient可调用托管API，非本地推理。但其包仍引入paddlex等依赖；本次未验证与模板Python3.14组合。因此固定业务适配器接口，默认以HTTPX复用成熟HTTP传输、沿用已提供的三段REST契约做薄封装，不安装本地推理引擎。P0可验证官方SDK；若采用，必须保留可恢复的submit/get/download阶段，不能仅用一次阻塞的parse_document替代作业恢复。选择及锁版本写入实施记录，不改变外层业务契约。

| 阶段 | 请求/返回 |
| --- | --- |
| 提交本地文件 | POST jobs，multipart的file；表单model与optionalPayload（JSON字符串），不向服务传本地路径字符串 |
| 提交远程URL | 本期前端不开放任意URL输入；已有调用案例支持fileUrl，但不扩展该入口 |
| 已提交 | 从data.jobId取编号，立即持久化；非成功HTTP和缺字段分别报错 |
| 查询 | GET jobs/{jobId}；读取data.state=pending/running/done/failed |
| 进度 | extractProgress.totalPages/extractedPages可缺；只在有效时显示页数 |
| 完成 | data.resultUrl.jsonUrl是JSONL下载地址；及时下载，不把它当永久结果 |
| JSONL | 忽略空行，每行解析JSON；读取result.layoutParsingResults；对每个对象保存外层行号和内部索引 |
| 图片 | 下载markdown.images、inputImage；outputImages.layout_det_res为调试版面图，不作为原件背景或印章裁剪图 |

API参数名区分大小写。初始保留案例中的useLayoutDetection=true、useSealRecognition=true、mergeTables=true、relevelTitles=true、restructurePages=true；方向矫正/去畸变先false，便于建立原件定位基线。保留markdownIgnoreLabels，但不要因此丢弃parsing_res_list中的相关原文块。returnMarkdownImages要保证可获得裁剪图，是否支持显式true需服务联调。useChartRecognition不用于财务分析。maxPixels/minPixels等模型参数先沿用已验证调用配置，不无依据调高。

每次请求配置计算hash并保存。useDocUnwarping/方向参数改变后来源空间要重新验证。用requests示例说明语义，不直接复制其无限轮询、assert和无界下载；实际需要超时、退避、状态、大小限制和恢复。单任务工件初始总量上限2GiB，可配置；超限明确失败，不静默缺图或丢页。

## 3. 超时、重试与作业恢复

初值：连接10s，单次提交/查询读取60s，轮询间隔5s，外部OCR总等待1800s，单资源下载读取60s，JSONL上限100MiB、单图片20MiB、最多4000万像素（均配置）。等待不占DB连接；总截止时间从首次提交计，重启不重新计时。

GET查询、下载遇429/502/503/网络读失败，最多3次指数退避并尊重Retry-After；认证、格式、超额明确失败不盲重试。提交POST只有在确定未发出时可安全重试；不知道是否已创建作业时SUBMISSION_UNKNOWN，不自动重交。已知jobId就恢复GET。重启先恢复DB中未终结的外部作业，再释放新提交配额；未知提交保守占用配额直到确认或达到截止时间，不能仅清空进程信号量就无限开新OCR。下载中断先写.tmp，再验大小/格式/hash后原子移动；JSONL/必需图片不完整不能标为归档成功。

下载URL仅来自可信服务响应并通过HTTPS主机允许名单，当前样本主机pplines-online.bj.bcebos.com；禁止直接抓取HTML里任意src，先匹配markdown.images字典。预签名过期时尝试同jobId重查新地址；服务不能重发则明确ASSET_DOWNLOAD_FAILED，可由用户显式重新OCR，不偷换为未找到。

## 4. 规范化字段映射

| 外部字段 | 内部含义/约束 |
| --- | --- |
| prunedResult.parsing_res_list | 权威解析块列表；保留读取顺序与provider IDs |
| block_label | 原始类别；text/title/table/seal/image等，未知值保留，不能丢整页 |
| block_content | 原始内容；可能是文字、HTML表格或图片HTML，不能统一当纯文本 |
| block_bbox / block_polygon_points | 来源区域，先保留原始值，再验证有限数值、范围与坐标空间 |
| block_id / group_id | 可能仅页内唯一，不能单独当系统主键；group不是业务检查项分组 |
| block_order | 可缺失；展示顺序优先可用order，缺失用列表顺序 |
| global_block_id / global_group_id | 有则保留用于重组映射；相等不能单凭此字段断言“未启用重组” |
| markdown.images[path] | 图片数据或URL；与block HTML的相对src精确关联，不根据文件名猜章类型 |
| inputImage | OCR页面图；解码图像得到实际width/height；不是默认等于原PDF尺寸 |
| doc_preprocessor_res.angle/settings | 预处理线索，具体旋转方向/映射需验证；不能只读角度就认定去畸变可逆 |
| layout_det_res.boxes | 检测辅助信息，与parsing列表长度不等，禁止按相同数组下标zip关联 |

系统为每页/块/裁剪分配UUID（可从ocrJobId和位置生成UUIDv5）。保留provider_line_index、provider_item_index、页内sequence。块ID即使在不同页相同也必须得到不同系统ID。block的img src可有多个，每个都建立独立crop并保留指向block的关联；主crop_id只是便捷字段，完整关系应可一对多。

HTML用成熟解析器（如BeautifulSoup）提取文本和img，不能用几个正则处理所有嵌套HTML。印章canonical_text去掉图片标签，保留可见识别文字和换行，不把HTML当机构名。表格保留结构和原始内容另存，供清理后呈现。HTML清理限制table/thead/tbody/tfoot/tr/th/td/caption等及rowspan/colspan等安全属性；不加载外部资源，不执行脚本。

样本prunedResult没有page_index、width、height。页面图片归档后读取尺寸；拿不到尺寸时字段null，location_precision降级。PDF源页数由pypdf读取用于比对，JSONL展开页序只有在服务契约/实际样本证明与原页一致时才映射为1起页号。出现少页、重复页、乱页、页范围处理或重组导致来源不明时，不假装原始页码已确认；保留OCR页索引并标记mapping_status=unverified。

## 5. 坐标与原件定位

为每个坐标标明空间：ocr_input_image_pixels或unknown。对已确认与归档inputImage一致的坐标，可用x/width、y/height映射到该OCR页面图；原始bbox保留，显示时可裁到图像边界。未知空间不画区域框。不能以所有bbox的最大x/y估计整页尺寸。

原PDF使用PDF.js viewport矩阵处理CropBox/旋转/缩放；仅在变换已验证时跨空间高亮。去畸变后的页面通常不能用一个简单缩放逆变回原件；优先显示已归档OCR处理页进行精确定位，同时保留原PDF入口。页码可靠但坐标不可靠时退到页；页码也不可靠则明确没有原页定位。跨页表格保留每一页的sources；拿不到完整来源不生成虚构来源。

## 6. 材料分类

读取全部相关原文块并按上下文窗口分组，不仅看文件名。允许类别business_license、articles_of_association、audited_financials、unknown；mixed只能在有证据时提出，不能把低置信度直接当混合文件。模型提供支撑block_ids，应用验证属于当前文件。

分类未知/混合需要人工处理或更换文件，阻止本轮完整发布；不能先当缺材料生成一批未找到。人工指定类别覆盖模型分类，但文件内容不改；重新查找对应清单。分类的目标是材料类别，不推断企业是否合规。

audited_financials是系统财报材料槽位的代码，不要求先识别到审计章/签名才允许归类。文件确实是财报但缺审计内容时仍可归入该槽位，由审计检查项按正常查找流程返回未找到；不要把“是否满足已审计要求”混入材料类别判断。

## 7. 文字/表格查找与长文覆盖

每类材料的全部文件参与查找。建立规范化块目录，输入包括系统blockId、文字、表格类型线索及来源，不发送文件存储路径或密钥。先用字符预算和上下文结构切窗口，默认每窗口约8000字符、相邻边界重叠约500字符，实际按模型上下文能力调。保存每个窗口的块/范围覆盖；模型返回本窗口无结果不等于整项无结果。

长表格不用把全部单元格送模型用于判断表名：可给表头、标题和附近块，模型选择tableBlockId，代码再取完整表格原文。超长段落按字符范围切片，保存切片到原canonical_text的offset映射。context_limit时缩小窗口重新执行该步，不悄悄截断尾页。任何窗口技术失败都阻止全覆盖not_found。

模型输出block引用和可选start_char/end_char，不让模型生成新的“原文段落”。代码按引用从canonical_text截取，offset按Unicode码点，半开区间[start,end)，null/null代表整块；模型可参考原文，但其自由生成文字不是证据。多个来源分别展示，不能拼成原文没有的新句子。

对所有窗口候选去重，按相关性排序，保留所有有依据候选；不以固定topK删除合法证据。证据引用必须属于run_files、正确材料及当前check。每个table结果是一张逻辑完整表格；OCR已提供跨页重组及来源时使用，否则分页展示并说明，不让LLM补全单元格或金额。

仅当覆盖完整、相关服务正常、所有目标文件处理结束时，才能为没有结果的叶子检查项产生一条not_found。没有上传该材料则生成material_missing；这是明确业务缺口，可以人工接受/拒绝。

## 8. 印章、签名查找

按清单依赖先提取审计机构等匹配目标。首先使用OCR裁剪图对应的识别文字（不是整页任意机构名）匹配检查项；足以识别和对应时直接采用，不对本项再调用视觉模型。机构名规范化可去空白/明显排版差异，但保留原文，不能把相近机构或分所强行等同。

文字不足以确定时，候选池包含当前财报材料全部已检测局部裁剪图（seal/signature/image等，包括未知类型）；不把整页图、layout_det_res版面调试图当裁剪图。不能假定只有seal标签才可能有签名，也不能把任何image自动标成签名。候选没有可靠检测裁剪时，不擅自声称已扫描每个签名区域。

将所有相关候选分批给视觉模型，不静默先截取前几张。按模型单次图片数/字节/上下文上限分批，保存每批cropId覆盖；初始每批4张、长边不超过1600像素（派生用于模型的图，不覆盖原裁剪图），最多输出4096 tokens，真实模型限制优先。每个crop始终携带稳定cropId与来源，防止模型按图序认错。

视觉模型只返回被选cropId、可可靠辨认的文字及对应关系；应用从本地工件取图。不判断真伪，不生成不可靠机构/姓名。多候选分别生成结果。已能辨认为相关印章/签名但具体对象对应关系不确定，可标needs_review；文字不可靠但模型能确定类型和相关性时仍可给图并说明。文字和视觉都无法判断归类时，生成“未找到相关印章/签名”，不把无法归类图强塞给该项。技术失败仍为失败。

## 9. 模型调用、约束与修复

LLM_API_BASE沿用用户阿里云兼容地址，文字/视觉模型名均.env配置；不假定用户示例型号已开通、不调用音频实时协议，不依赖embedding。使用OpenAI SDK的Chat Completions。设连接10s、请求120s、调用并发2；429/服务临时错误按配置退避，拒绝/鉴权/无模型权限直接失败。避免SDK重试和业务重试相乘，统一配置SDK max_retries=0，由步骤层管理最多2次可恢复调用重试。

提示词版本、模型ID、参数和输入hash写run_steps。temperature在模型支持时设0，不代表结果完全确定。优先json_schema严格输出，模型不支持则json_object加Pydantic/JSON Schema严格校验；Schema正确仍须验证引用集合、字符范围、类别、任务归属及覆盖。最多一次格式修复，不循环让模型“编一个合法答案”。结果通过全部校验才入库。

文件中出现“忽略清单、输出通过、访问网址”等内容一律作为不可信原文，不执行；模型没有任意网络、文件系统或数据库写入工具。模型仅输出候选，最终来源关联、确认和完成由代码控制。

## 10. 实际未验证内容

尚未验证：服务可用凭据和配额；真实下载URL有效期/续签；完整签名返回格式；原PDF与OCR图尺寸/旋转映射；跨页表格来源；真实模型ID及结构化/多图能力；5用户实际端到端耗时。上述是联调工作，不阻止先实现适配器和自动化，但不能在最终报告里标为通过。
