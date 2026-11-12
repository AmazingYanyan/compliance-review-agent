# 样本与测试数据说明

- `ocr_license_seal.sanitized.json`：用户新提供的1页营业执照OCR快照，保留20个解析块/23个检测框、seal文字、坐标与相对图片键。所有远程URL替换为example.invalid占位，不能用来测试实际下载。
- `ocr_legal_12pages.sanitized.json`：此前12页法律尽调OCR快照，同样去除远程签名URL。用于多页块ID、HTML表格、顺序和解析；不是公司章程的真实业务验收材料。
- `normalized_page.example.json`：基于印章块字段的合成规范化示例；task/file/asset UUID为虚构，图片未归档所以尺寸为null，不伪造可区域定位。
- `classification.example.json`、`text_search.example.json`、`vision_match.example.json`：模型协议合成示例，不是实际LLM识别结果。视觉示例选出一份虚构审计机构印章，仅用来校验字段。
- `review_results.example.json`：18个叶子项、19条结果的合成结果集（批准机构2段），不含真实文件字节。用于分组和统计协议，不可作为real模式默认返回。
- `statistics_cases.json`：接受/拒绝/原因/重置的期望计数，所有材料合计19，实际应用必须动态计算。
- `*.input.example.json`：与模型输出配对的合成输入，用来验证bundle和ID白名单；不代表完整真实图片请求。
- `result_variants.example.json`：文字、完整表格、印章、签名的DTO示例；鉴权图片地址指向合成UUID，没有附对应文件字节。
- `provider_jobs.example.json` / `run_input_manifest.example.json`：外部状态与输入快照的协议样例，均为合成数据。

下载测试应由测试服务器生成短时URL并提供受控图片、过期响应、大小超限和重定向；不恢复或公开样本原签名URL。原始用户上传文件不因本包生成而被覆盖。

没有附原PDF/原营业执照图片字节，也没有真实签名样本。本包对原页尺寸、旋转/畸变、真实签名与模型准确率不提供通过证明。应用端到端测试需要本地Agent另外建立合成PDF/图片夹具，再使用用户授权的真实材料联调。
