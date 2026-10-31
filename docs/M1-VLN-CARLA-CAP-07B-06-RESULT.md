# M1-VLN-CARLA-CAP-07B-06-EXEC — Final Parking Verification & Task Completion

Date: 2026-10-31
Scope: bay03 final parking verification and completion gate on CARLA
UndergroundCarPark. The run re-establishes the accepted Entry → Refinement
chain in one CARLA process (the previous stage cleaned up its vehicle), stops
the vehicle, and runs the independent `FinalParkingVerifier` and
`ParkingCompletionGate`.

**Verdict: PASS — `PARKING_COMPLETED`. `parking_completed = true`.**

All 30 pre-declared verifier checks pass, the gate issued the only
`PARKING_COMPLETED` decision, and the task state is `PARKING_COMPLETED` for
task `cap07b-06`, vehicle actor 687, target `bay03` / `park_slot`.
This is CARLA simulation evidence, not a production safety certification.

## 1. 实施摘要

- 新增独立领域验证器 `FinalParkingVerifier`（`src/vln/parking/completion.py`）：
  只读校验真实 transform/bbox/velocity/collision/bay geometry/obstacle
  evidence/Entry artifact/Pose Ready artifact/因果链，**永不**设置
  `parking_completed=true`。
- 新增唯一完成 Gate `ParkingCompletionGate`：只有 verifier 结果全条件通过、
  身份一致、未过期、未篡改时才签发 `PARKING_COMPLETED`；Taichu、CARLA
  执行器、Entry/Alignment/Refinement Skill 和普通状态更新均不能直接签发。
- 修复 CAP-07B-05 遗留的逐 tick floor guard 死参数：真实 refinement 两次
  Kernel segment 均以 `floor=0.052 m` 每 tick 读取真实 bbox/transform 执行；
  本轮最小 clearance 为 0.052 m（reverse）和 0.160 m（forward），未触发。
- 新增 `scripts/carla_cap07b06_final_verify.py`：只读 preflight →
  （必要时）复用 CAP-07B-04/05 既有链路重建 Entry → Refinement →
  只读最终验证 → Gate → evidence。
- 真实运行结果：Entry PASS `ENTRY_COMPLETED`；Refinement PASS
  `PARKING_POSE_READY`；Final verifier `FINAL_PARKING_VERIFIED`；Gate
  `PARKING_COMPLETED`。最终位姿与 CAP-07B-05 验收终态完全一致（0.0 m /
  0.0°）。
- 第一次真实运行因 runner 漏导入 `FinalParkingInputs` 在最终验证阶段抛
  `NameError`；Entry/Refinement 本身均 PASS。Gate 正确拒绝“缺少 verifier
  result”的情况（`verifier_result_missing`），顶层结果 `FAIL`、
  `parking_completed=false`。该失败 evidence 完整保留在
  `docs/evidence/vln-carla-cap-07b-06-attempt1-runner-nameerror/`。修复导入后
  的单次重跑 PASS。未放宽任何阈值，未因验证失败自动移动车辆。

## 2. 初始 Git 状态

### VLN-AVP

- branch `main`；HEAD `2d88614bff8ccef2897b8178bf30a2835166c8b0`。
- 工作树在运行开始前已有 272 条 `git status --short` 条目（既有修改、报告、
  evidence 和未跟踪目录）；本阶段未执行 `reset`、`clean`、`stash`、commit 或
  push。
- 本阶段所有编辑位于既有未跟踪文件/目录中；没有修改任何已跟踪文件。

### Embedded `VLN-AVP/Agent-Kernel/`

- `git status --short -- Agent-Kernel/`：空。
- 已跟踪快照 440 个文件，最后提交 `c25f28e`。
- `git diff --stat HEAD -- Agent-Kernel/` 与
  `git diff --name-status HEAD -- Agent-Kernel/`：空。
- 未修改、未清理、未替换、未重建。

### Sibling clone

- 任务中给出的 `/home/gaosong/Agentic_Program/Agent-Kernel` 不存在。
- 机器上实际存在的 sibling 是
  `/home/gaosong/workspace/Agentic_Program/Agent-Kernel`，branch `main`，
  HEAD `dcd1341d768cacd50af640fb47ab627dbf3e1f5e`，工作树干净。
- 只读访问，未修改、未推送。

## 3. 修改文件

新增：

- `src/vln/parking/completion.py` — `FinalParkingVerifier`、
  `ParkingCompletionGate`、阈值、证据结构、唯一完成签发路径。
- `scripts/carla_cap07b06_final_verify.py` — CAP-07B-06 真实 runner。
- `tests/vln/test_final_parking_verification.py` — 67 个 verifier/gate 测试。
- `tests/vln/test_entry_terminal_floor_guard_drive.py` — 3 个 fake-session
  逐 tick guard 集成测试（CARLA venv 下用 `unittest` 运行）。

调整（均为既有未跟踪文件）：

- `src/vln/carla/entry_terminal.py` — 新增 `BoundaryFloorGuard` 与
  `boundary_floor_guard()`；在 `__all__` 中导出。
- `src/vln/carla/parking_geometry.py` — 新增公共 `point_in_polygon()`，
  供 guard 复用；未改变既有调用方。
- `scripts/carla_cap07b04_entry.py` —
  - `_drive_terminal_phase` 每 tick 真实读取 bbox/transform 并执行 floor
    guard；
  - 记录 `boundary_floor` 和每 tick `boundary_floor_guard`；
  - `after_entry` 额外传递 `collision_monitor`（碰撞传感器角色、id、起始
    frame/UTC）。
- `scripts/carla_cap07b05_refine.py` —
  - 接收并记录 `collision_monitor`；
  - 在 `entry_reestablished` 中记录全精度
    `entry_completion_inputs` 与 `entry_first_motion_frame`，用于最终
    verifier 复算 `entry_completion_id` 的因果链。
- `tests/vln/test_entry_terminal.py` — 新增 9 个 floor guard 单元测试。

Evidence：

- `docs/evidence/vln-carla-cap-07b-06/` — 最终 PASS evidence。
- `docs/evidence/vln-carla-cap-07b-06-attempt1-runner-nameerror/` — 第一次
  真实运行（runner NameError）的完整失败 evidence。

未修改 CAP-07B-04/05 历史 evidence，未 commit/push。

## 4. 复用的既有组件

- `vln.carla.parking_geometry.Footprint`、
  `footprint_polygon_clearance()`、`footprint_clearance()`、
  `point_in_polygon()`。
- `vln.carla.parking_verdict` 中已声明的 bay03 polygon/center、足迹、
  position 0.25 m、heading 5.0°、stop 0.05 m/s、stability drift 0.02 m、
  painted-boundary 0.05 m。
- `vln.parking.entry.verify_entry()` 与 Entry artifact 结构。
- `vln.parking.refinement.verify_refinement()`、
  `compute_entry_completion_id()` 与 `PARKING_POSE_READY` artifact 结构。
- CAP-07B-04 Entry runner、CAP-07B-05 Refinement runner、`CarlaExecutionBridge`、
  `parking.move` single-use permit、Kernel Host correlation。
- `vln.carla.session.cleanup_session()` 与既有 CARLA 同步设置恢复。
- CAP-07B-03 已验收的 `ALIGNMENT_COMPLETED` artifact 作为 Entry 重建起点。

没有复制平行几何/授权实现；最终验证只复用现有几何与 artifact 结构。

## 5. `FinalParkingVerifier` 实现

文件：`src/vln/parking/completion.py`。

输入（均要求来源和 frame 关联）：

- task/bay/slot、entry task、refinement task、entry authorization id；
- 当前真实 `VehicleSnapshot`（actor id/type、transform、bbox extent/location、
  velocity、speed、frame、alive）；
- 真实 bbox 足迹、配置足迹；
- bay polygon/center/heading；
- obstacle evidence（历史静态点 + live ray probe）；
- collision evidence（传感器可用性、监测起始 frame/UTC、首次运动 frame、
  task 事件、最终窗口事件）；
- 连续 stability samples；
- Entry artifact + canonical SHA-256；
- Pose Ready artifact + canonical SHA-256，其中包含全精度
  `entry_completion_inputs`。

检查（30 项，全部预声明）：

| 类别 | 检查 |
|---|---|
| 输入 | `inputs_complete` |
| 身份 | `task_identity`, `bay_identity`, `slot_identity`, `vehicle_identity`, `vehicle_geometry_consistent` |
| Artifact | `entry_artifact_valid`, `entry_artifact_hash`, `pose_ready_artifact_valid`, `pose_ready_artifact_hash`, `stage_chain_causal`, `current_state_matches_pose_ready` |
| 几何 | `footprint_inside_bay`, `boundary_clearance`, `lateral_error`, `longitudinal_error`, `heading_error`, `position_tolerance` |
| 障碍 | `obstacle_evidence_present`, `obstacle_clearance` |
| 碰撞 | `collision_sensor_available`, `collision_history_complete`, `no_collision` |
| 停止 | `velocity_readable`, `stopped`, `stability_samples`, `stability_position_drift`, `stability_heading_drift` |
| 稳定性 | `actor_stable`, `bay_stable` |

关键实现点：

- **不使用中心点代替 footprint**：同时计算
  `actor` 足迹、`bbox_center` 足迹（应用 CARLA `bounding_box.location`
  偏移）和配置足迹；三者都必须完整在 bay 内，boundary/obstacle clearance
  取三者最小值。
- **真实 bbox 优先**：使用 CARLA 实际
  `extent=(2.503022, 0.940476, 0.770157)`；配置足迹为
  `(2.503, 0.94, 0.77)`；差值为 `0.000476 m`，阈值 0.01 m。保守使用较严格
  的 clearance。
- **坐标约定**：bay heading `π`（west/nose-in），
  `forward=(cos h, sin h)`，`left=(-forward_y, forward_x)`；lateral 为左向
  分量，longitudinal 为前向分量；heading error 为
  `wrap(yaw - bay_heading)`。
- **Artifact 因果链**：Pose Ready artifact 携带
  `entry_completion_inputs`（全精度 Entry pose、boundary、heading、route
  hash、Entry authorization id、Entry task id、parking task id、actor id）。
  Verifier 用这些输入重新计算 `entry_completion_id`，并要求：
  - 复算值 == Pose Ready artifact 的 `entry_completion_id`；
  - chain 中的 entry task/parking task/actor/authorization/route 与当前输入
    和 Entry artifact 一致；
  - chain 中全精度 pose 与 Entry artifact 舍入 pose 的差 ≤ 0.01 m / 0.01°；
  - `entry_frame ≤ pose_ready_frame ≤ current_frame`，且
    `current_frame - pose_ready_frame ≤ 2000`。
- **失败闭合**：任何缺少输入、非有限数、几何异常或 hash 不一致都返回
  `NOT_COMPLETED`，不抛异常；`parking_completed` 始终为 `false`。

## 6. `ParkingCompletionGate` 实现

- 唯一允许产生 `parking_completed=true` 的位置。
- 输入必须是 `CompletionRequest(source=FINAL_PARKING_VERIFIER, ...)` 和
  有效 verifier result；其他 source（Taichu、CARLA executor、Entry、
  Alignment、Refinement、state update）直接 `NOT_COMPLETED`。
- 重新校验 verifier result 的 canonical SHA-256；任何字段篡改（保留旧
  hash）都会拒绝。
- 要求：
  - `decision == FINAL_PARKING_VERIFIED`；
  - `verification_passed == true`；
  - `parking_completed == false`（verifier 不得自行签发）；
  - `failed_checks` 为空，30 项 checks 全部 true；
  - task/bay/slot/vehicle actor 与请求一致；
  - verifier version 为 `vln.parking.final_verification.v1`；
  - 当前 frame 不早于验证 frame，且 `current_frame - verification_frame
    ≤ 2000`；
  - `now - verification_timestamp ≤ 300 s`。
- 通过后签发 `PARKING_COMPLETED`、`parking_completed=true`，并写出
  `task_state`（stage/source/gate_decision_id/verifier_result_sha256）。
- 相同请求重复提交返回同一 `decision_id`，`idempotent_replay=true`。
- `reject_ungated_parking_completion()` 与 `require_gate_decision()` 提供
  旧/新状态写入路径的统一拒绝/校验入口。

## 7. `PARKING_COMPLETED` 所有写入路径检查

- 全仓 `src/vln` 与 `scripts` 源码扫描未发现除 `completion.py` 之外的
  `parking_completed=True` / `decision="PARKING_COMPLETED"` 写入。
- 既有 CAP-07B-04/05 结果、Kernel bridge、Kernel Host 和脚本只写
  `parking_completed=false`。
- 新增回归测试
  `test_no_code_path_outside_gate_writes_parking_completed_true` 对
  `src/vln` 和 `scripts` 做静态扫描，排除 `completion.py` 本身。
- 第一次真实运行（runner NameError）中 Gate 在缺少 verifier result 时返回
  `NOT_COMPLETED`，`reasons=["NameError: ...", "verifier_result_missing"]`，
  `parking_completed=false`；这次失败 evidence 保留，证明 fail-closed 路径
  真实生效。

## 8. CAP-07B-05 死参数修复

`_drive_terminal_phase(..., min_boundary_clearance=...)` 之前只接收参数、
从未读取。本阶段：

- 新增纯函数 `boundary_floor_guard()`（`entry_terminal.py`）：
  - 每 tick 使用当前 `state`（不是上一 tick）和当前
    `ego.bounding_box`；
  - 应用 bbox center offset；
  - 计算四角、footprint 是否完整在 bay 内、`footprint_polygon_clearance`；
  - `clearance > floor` 通过；`clearance == floor`（1e-9 容差）通过；
    `clearance < floor` 返回 `boundary_below_floor`；
  - transform/bbox 不可读返回 `boundary_state_unreadable`；
  - clearance 非有限/几何异常返回 `boundary_clearance_invalid` /
    `boundary_geometry_invalid`；
  - 记录 frame、transform、bbox、四角、clearance、floor。
- `_drive_terminal_phase` 在每 tick 的碰撞/box/buffer/obstacle 检查之后、
  下发控制之前调用 guard；触发后立即 break，循环外立即 `brake=1.0`，
  `phase_success=false`，不执行剩余 segment。
- 真实 refinement 证据
  （`refinement_reestablish/result.json`）：

| Round | Phase | floor | min clearance | triggered | stop |
|---|---|---:|---:|---|---|
| 1 | `TERMINAL_REVERSE_ALIGN` | 0.052 m | 0.052 m | false | `distance_limit` |
| 2 | `TERMINAL_FORWARD_RETURN` | 0.052 m | 0.160 m | false | `slot_x_reached` |

- 未放宽任何阈值。CAP-07B-04 自身的 terminal segment 不传该参数，仍然依赖
  既有 buffer/obstacle 检查；报告不再声称它对那些 segment 提供 floor 保护。

测试：

- `tests/vln/test_entry_terminal.py`：9 个新单元测试覆盖通过、等于 floor、
  低于 floor、越界、不可读状态、非法 floor、非法几何、bbox offset、
  failure record。
- `tests/vln/test_entry_terminal_floor_guard_drive.py`：3 个 fake-session
  集成测试直接驱动真实 `_drive_terminal_phase`，证明：
  - floor 低于当前 clearance 时在**任何 throttle 之前**停止；
  - SAFE_STOP 后 `phase_success=false`，调用方不会执行后续 segment；
  - bbox 读取失败时 fail-closed。

## 9. 单元测试和集成测试

- 新增 verifier/gate：67 个测试全部通过。
- 新增 floor guard 单元：9 个测试全部通过。
- fake-session guard 集成：CARLA venv `unittest` 3/3 通过；默认 pytest 环境
  因无 CARLA Python API 跳过 3 个（预期）。
- CAP-07B 相关回归子集（10 个测试文件：final verification、entry
  terminal、entry verification、refinement、parking geometry/verdict、
  kernel bridge、alignment authorization、autonomous parking、recovery
  skill）：**221 passed**。
- 本轮 evidence 中捕获的 6 文件目标测试（final verification、entry
  terminal、entry verification、refinement、parking geometry/verdict）：
  **156 passed**。
- 全量测试：**1511 passed, 3 failed, 168 skipped**。
  - 3 个失败是 CAP-07B-05 已记录的既有失败：两张 `images/` 文件数断言
    （期望 4，实际 12）和 NAV-09 旧断言（`Relative position`/`Next
    direction` 强制相等）。
  - 168 skips 主要为环境门禁（无 `VLN_KERNEL_HOST_EXE`、无真实模型 flag；
    另有 3 个无 CARLA Python API 的 fake-session guard 测试在默认环境跳过）。
- 测试原始输出：`docs/evidence/vln-carla-cap-07b-06/test_output.txt`。

## 10. 真实 CARLA 验证过程

1. **只读 preflight**（`read_only_preflight.json`）：
   - server `0.10.0`，map `Carla/Maps/UndergroundCarPark`，frame 0，
     synchronous 0.05 s；
   - actor_count 0，vehicle_count 0，vln_actor_count 0；
   - `usable=false`，原因 `world_has_no_vehicle; stage chain must be
     re-established`。
   - 未 spawn、未 tick、未改设置。
2. **重建前置状态**（同一 CARLA 进程）：
   - 从已验收 CAP-07B-03 `ALIGNMENT_COMPLETED` artifact 出发，复用
     CAP-07B-04 Entry 链路；
   - Entry 4 个授权 segment，PASS `ENTRY_COMPLETED`，0 collisions；
   - 同一进程内复用 CAP-07B-05 Refinement 链路：2 个授权 segment，
     PASS `PARKING_POSE_READY`，0 collisions。
3. **只读最终验证**：
   - 停车状态下附加最终 collision sensor；
   - 连续 10 个 brake tick 采样（不做任何 throttle）；
   - 读取真实 transform/bbox/velocity；
   - 32 条 live ray（16 方向 × 2 高度，2.8–5.8 m）+ 29 个历史静态点；
   - 构建并校验 Entry/Pose Ready artifact 与因果链；
   - `FinalParkingVerifier` → `ParkingCompletionGate`；
   - 写全部原始 evidence。
4. **清理**：Entry runner 的 `cleanup_session` 报告
   `destroy_errors=[]`、`leftover_vln_actors=0`；运行后只读复查
   actor_count 0、vehicle_count 0、vln_count 0、sync 0.05。
   console 中 3 条 `failed to destroy actor 687/688/689` 是已随父 actor
   失效的子 sensor 的销毁提示；cleanup 自身无错误、世界无残留。
5. 未重启 CARLA 或 Taichu；未修改模型权重/服务参数；未修改 sibling clone。

### 第一次真实运行（失败，已保留）

- 时间：2026-10-30T16:51Z 左右。
- Entry PASS、Refinement PASS；最终验证阶段 runner 抛
  `NameError: name 'FinalParkingInputs' is not defined`（漏导入）。
- Gate 收到缺失 verifier result，返回 `NOT_COMPLETED`
  （`verifier_result_missing`），顶层 `status=FAIL`、
  `parking_completed=false`。
- 失败 evidence：
  `docs/evidence/vln-carla-cap-07b-06-attempt1-runner-nameerror/`。
- 修复：在 runner 中导入 `FinalParkingInputs`；用第一次运行的真实
  Entry/Refinement artifact 做离线 verifier 复核，确认 30 项 checks 全部
  通过、Gate 可签发；随后进行一次修复后真实重跑。
- 这不是阈值放宽或自动重试失败判定；是软件缺陷修复后的重新执行。第一次
  失败结果未被删除或覆盖。

## 11. 初始和最终真实状态

| 阶段 | frame | x | y | yaw | speed | boundary | heading error |
|---|---:|---:|---:|---:|---:|---:|---:|
| Entry 初始（重建起点） | 10770130 | -3.9963 | -17.1861 | -89.5378° | 0 | 0.193 | 90.4622° |
| Entry 完成 | 10771629 | -9.4864 | -21.2488 | -176.5466° | 0 | 0.052 | 3.4534° |
| Refinement 初始 | 10771634 | -9.4864 | -21.2488 | -176.5466° | 0 | 0.052 | 3.4534° |
| Refinement 完成 / Pose Ready | 10772655 | -9.4816 | -21.1966 | -177.8625° | 0 | 0.161 (config) | 2.1375° |
| Final verification | 10772665 | -9.4816 | -21.1966 | -177.8625° | 0 | **0.160 (actual bbox)** | **2.1375°** |

- 最终 actor：687，`vehicle.dodge.charger`。
- 当前最终位姿与 CAP-07B-05 历史验收终态：
  **0.0 m / 0.0°**（独立复算）。
- Entry 重建最终位姿与历史 CAP-07B-04 验收终态：
  **0.0 m / 0.0°**（`entry_reestablished.pose_gap_m=0.0`,
  `historical_pose_gap_m=0.0`, `historical_heading_gap_deg=0.0`）。

注意：本轮是**重新执行**的 Entry/Refinement 链，不是把历史位姿当作当前
状态读取。新的 Entry authorization 产生了新的
`entry_completion_id=0887868af152908b2271cc67695c61ccfc01d0591573f97042a573f65fcb895a`；
历史 CAP-07B-05 的 `94c984...` 绑定的是上一次 Entry authorization。两者
pose 完全一致，但 artifact/authorization 属于本轮真实执行。

## 12. footprint 和 clearance

最终 CARLA bbox（`carla_final_state.json`）：

- extent：`(2.503022, 0.940476, 0.770157)` m；
- location offset：`(-0.006238, 0.0, 0.762784)` m；
- 与配置足迹 `(2.503, 0.94)` 的最大半宽/半长差：
  **0.000476 m**（阈值 0.01 m）。

真实足迹四角（`final_verification_result.json`）：

```
(-11.9478, -22.2298)
(-12.0180, -20.3501)
(-7.0154, -20.1634)
(-6.9453, -22.0431)
```

bbox-center 足迹四角（应用 CARLA offset）：

```
(-11.9416, -22.2295)
(-12.0117, -20.3499)
(-7.0092, -20.1632)
(-6.9390, -22.0428)
```

配置足迹四角：

```
(-11.9478, -22.2293)
(-12.0179, -20.3506)
(-7.0154, -20.1639)
(-6.9453, -22.0426)
```

三者均完整在 bay03 polygon
`x∈[-14.4,-4.0], y∈[-22.39,-19.89]` 内。

| Clearance | 值 | 阈值 | 结果 |
|---|---:|---:|---|
| actual bbox boundary | **0.160 m** | ≥0.05 | pass |
| bbox-center boundary | 0.160 m | ≥0.05 | pass |
| config boundary | 0.161 m | ≥0.05 | pass |
| obstacle（live+historical） | **0.753 m** | ≥0.20 | pass |
| lateral error | **0.0566 m** | ≤0.25 | pass |
| longitudinal error | **-0.0184 m** | ≤0.25 | pass |
| heading error | **2.1375°** | ≤5.0 | pass |
| distance to bay centre | **0.0595 m** | ≤0.25 | pass |

`limiting_footprint = "actor"`；`boundary_clearance_m=0.160` 是三者最小值。

复算方式：用 `carla_final_state.json` 的 transform/bbox（或
`final_verification_inputs.vehicle`）重建 footprints，用
`vln.carla.parking_geometry.footprint_polygon_clearance()` 对
`final_verification_inputs.bay_polygon` 计算；lateral/longitudinal/heading
使用 `final_verification_inputs.bay_heading_rad=π` 和 bay center。

## 13. obstacle / collision evidence

### Obstacle

`obstacle_evidence.json`：

- 历史静态点：29 个（`docs/evidence/carla-07a/geometry_probe.json`，
  CAP-07A 的 collision-mesh 采样；**不是**完整实时障碍物模型）。
- live ray probe：32 条（16 方向 × 2 高度 0.5/1.0 m，从 2.8 m 到 5.8 m），
  6 个 live hit，无 ray 错误。
- 合并去重后 35 个点；`source =
  "historical_static_samples+live_ray_probe"`，
  `live=true`。
- 最小 footprint 到障碍点距离 **0.753 m**（阈值 0.20 m）。
- 最近 live 点约为 `(-7.5017, -19.2167)`（北侧柱）；西墙点
  `x≈-14.5987` 距离更远。
- 覆盖限制：稀疏射线 + 历史静态采样，不是完整 occupancy grid；不能声称
  连续空间完整障碍物几何。

### Collision

`collision_evidence.json`：

- Entry collision sensor：role `vln_cap07b04_collision`，sensor id 688，
  monitoring start frame **10770125**，start UTC
  `2026-10-30T16:52:47.132149+00:00`。
- 首次 commanded motion frame **10770130**；传感器在首次运动前已附加。
- 最终验证 collision sensor：role `vln_cap07b06_collision`，sensor id 689，
  start frame 10772655，结束 frame 10772665。
- Entry+Refinement task collision events：**0**。
- Final verification window events：**0**。
- `evidence_gap=false`。
- 诚实限制：sensor 附加前的 50 个静止 spawn-settle tick 不在传感器覆盖内
  （无 commanded motion）；该缺口写入 limitations，不声称“全生命周期无碰撞”。

## 14. velocity / stability

`final_stability_samples.json`：

- 10 个连续 brake tick，frames `10772656..10772665`，间隔 0.05 s。
- 每个样本 `speed=0.0 m/s`，位置
  `(-9.4816, -21.1966)` 完全不变，yaw `-177.8625°` 完全不变。
- `max_speed=0.0`，`position_drift=0.0 m`，`heading_drift=0.0°`，
  `frame_monotonic=true`，`interval_ok=true`，`stable=true`。
- `actor_alive=true`，`actor_id_consistent=true`，actor_ids `[687]`。
- 最终 `velocity=(0,0,0)`，`speed=0.0`。
- 阈值：stop <0.05 m/s、position drift ≤0.02 m、heading drift ≤0.5°、
  样本数 ≥5；全部满足。

## 15. Entry 和 Pose Ready artifact 关联

| 字段 | 值 |
|---|---|
| Entry artifact SHA-256 | `10d627bcca0f8d8b0a09e9b111ae63ea7cd20cc6a539352d1d32ca5615f179bc` |
| Pose Ready artifact SHA-256 | `fcfa01c02d18eef15c9e1bd9ebb617dbcfdda4230005ec11d3bffd598664e21b` |
| Entry task | `cap07b-04` |
| Refinement task | `cap07b-05` |
| Entry authorization id | `0543b776f8e483fd450fbe156c28c28759f5871d75ee1435c5bbf1cc83785fd8` |
| Entry completion id | `0887868af152908b2271cc67695c61ccfc01d0591573f97042a573f65fcb895a` |
| Refinement plan hash | `65162862b2bbea16759ffbc94ba92652f927e2e5ec240b9f9378623f4904ae10` |
| Entry frame | 10771629 |
| Pose Ready frame | 10772655 |
| Verification frame | 10772665 |
| Vehicle actor | 687 |

因果校验：

1. Pose Ready artifact 携带全精度 `entry_completion_inputs`；
2. verifier 用其 `entry_task_id`、`entry_authorization_id`、
   `entry_route_hash`、`final_pose`、`final_boundary_clearance_m`、
   `final_heading_error_deg` 重新计算 `entry_completion_id`；
3. 复算值 == Pose Ready artifact 的 `entry_completion_id`；
4. chain 的 `parking_task_id=cap07b-06`、`vehicle_actor_id=687` 与当前
   Gate 请求一致；
5. chain 全精度 pose 与 Entry artifact 舍入 pose 的差 ≤0.01 m / 0.01°；
6. Entry frame ≤ Pose Ready frame ≤ verification frame，且最后一段 gap=10
   frame ≤2000。

所有 artifact 均在 `final_verification_inputs.json` 中保存原文，可独立复算
canonical SHA-256 和 `entry_completion_id`。

## 16. 最终完成判定

| 项 | 结果 |
|---|---|
| Verifier decision | `FINAL_PARKING_VERIFIED` |
| Verifier failed checks | `[]` |
| Verifier checks true | 30/30 |
| Gate decision | **`PARKING_COMPLETED`** |
| `parking_completed` | **`true`** |
| Gate decision id | `3e665243fcac41d5ca5655edff8219161dc1a0f93108e190518977f798f28f41` |
| Verifier result SHA-256 | `68147f8d043804adf07978c9041d54b9c85df1f690368297e3a07fd4ff329d51` |
| Task state | `cap07b-06` / `PARKING_COMPLETED` |
| Gate reasons | `[]` |
| Target | bay03 / park_slot |
| Vehicle actor | 687 |

## 17. 原始 evidence 文件清单

`docs/evidence/vln-carla-cap-07b-06/`：

- `read_only_preflight.json` — 运行前只读世界状态。
- `entry_reestablish/` — 本轮 CAP-07B-04 Entry 全部 evidence
  （initial/final state、verification、rounds、route、authorization、
  geometry、Kernel transactions、result）。
- `refinement_reestablish/` — 本轮 CAP-07B-05 Refinement 全部 evidence
  （initial/final、candidates、route、rounds、authorization、verification、
  geometry、Kernel transactions、result）。
- `carla_final_state.json` — 最终 transform/bbox/velocity/actor/frame。
- `final_stability_samples.json` — 10 个连续样本与 actor 证据。
- `collision_evidence.json` — Entry/final collision sensor 与事件。
- `obstacle_evidence.json` — 29 历史点 + 32 live rays + 6 live hits +
  合并结果。
- `artifact_chain.json` — 两个 artifact hash、completion id、plan hash、
  frames、actor。
- `kernel_correlations.json` — 6 个 `parking.move` 授权执行（4 Entry +
  2 Refinement），request/intent id、execution_status、transaction 存在性；
  最终验证只读、无 Kernel capability。
- `final_verification_inputs.json` — 最终 verifier 的全部原始输入
  （含完整 artifact 原文、chain、bay polygon、footprint、samples、
  obstacle、collision、tolerances）。
- `final_verification_result.json` — 30 项 checks、measurement、
  stability、obstacle、collision、limitations、result hash。
- `completion_gate_request.json` — Gate 请求与 verifier result hash。
- `completion_gate_decision.json` — Gate decision、task_state、
  decision_id、limitations。
- `task_state.json` — 最终任务状态。
- `result.json` — 顶层结果（status/decision/parking_completed/git/carla/
  verifier/gate/inputs summary）。
- `run.log`、`console.log` — 原始运行日志。
- `test_output.txt` — 目标测试、fake-session guard 测试、全量测试原始输出。

本轮没有新增相机图像：Entry/Refinement runner 未启用已有的 chase camera
观察路径；原始 CARLA transform/bbox/velocity/collision JSON 是权威证据。

`docs/evidence/vln-carla-cap-07b-06-attempt1-runner-nameerror/`：

- 第一次真实运行的完整失败 evidence（Entry/Refinement PASS、最终阶段
  NameError、Gate `NOT_COMPLETED`）。

CAP-07B-04/05 历史 evidence 未被覆盖。

## 18. 未解决问题

1. **历史 artifact 的全精度 id 不可复算**：CAP-07B-05 的
   `94c984...` 使用当轮未显式保存的全精度 `compute_entry_completion_id`
   输入；其 JSON artifact 中的 pose 已舍入到 4/6 位，独立复算会得到不同
   hash。本轮通过 `entry_completion_inputs` 显式保存全精度输入解决；历史
   evidence 不改写。这属于历史可复算性缺口，不影响本轮真实链。
2. **Obstacle 模型仍是稀疏的**：29 个历史点 + 32 条 live ray，不等于完整
   实时障碍物几何。若需要更强结论，需要完整 occupancy/碰撞网格查询。
3. **碰撞传感器覆盖缺口**：sensor 附加前的 50 个静止 spawn-settle tick 无
   传感器覆盖；无 commanded motion，但不能声称全生命周期无碰撞。
4. **稳定性是离散采样**：10 个 0.05 s 样本，不是连续时间严格证明。
5. **控制器目标速度不是硬上限**：CAP-07B-05 评审指出的 0.10 m/s 目标与
   实际峰值 ~0.14 m/s 差异仍存在；本轮没有新增速度声明。
6. **Agent-Kernel 无任务完成 API**：embedded snapshot 只暴露
   per-invocation execution status，没有 task lifecycle completion
   primitive；本轮未修改 Kernel，最终完成由 VLN-AVP Gate 的
   `task_state` 记录，Kernel correlation 通过 request/intent id 保留。
7. **单执行器、单目 RGB、仅仿真**：不构成生产安全认证。
8. **Floor guard 的数值分辨率**：guard 使用项目既有
   `footprint_polygon_clearance` 的 3 位小数（1 mm）几何分辨率；它不声称
   亚毫米或连续时间严格边界保护。比较规则为 `clearance + 1e-9 < floor`
   才触发，即与项目既有 measured-clearance 分辨率一致。

## 19. 能力范围和限制

- 本阶段能力：在真实 CARLA 中，从已验收 Alignment artifact 重建
  Entry/Refinement，独立校验最终停车姿态、完整 footprint、boundary/
  obstacle clearance、碰撞、速度与稳定性、artifact 因果链，并由唯一 Gate
  签发 `PARKING_COMPLETED`。
- 不包含：连续时间安全证明、完整实时障碍物建模、生产安全认证、
  真实车辆控制、CAP-08 内容。
- 最终结论仅适用于 CARLA UndergroundCarPark bay03、actor 687、
  `vehicle.dodge.charger`、当前世界状态（frame 10772665）。
- 不能把本轮结果外推为其他 bay、其他车辆或其他地图的完成证明。

## 20. Git 最终状态

- branch `main`；HEAD `2d88614bff8ccef2897b8178bf30a2835166c8b0`（未变）。
- 未 commit、未 push、未 reset、未 clean、未 stash。
- Embedded `Agent-Kernel/`：0 修改、0 diff。
- Sibling clone（实际路径
  `/home/gaosong/workspace/Agentic_Program/Agent-Kernel`）：未修改。
- 新增源码/测试/evidence 均为未跟踪文件；已跟踪文件无修改。

## 21. 明确声明

- **是否真实产生 `PARKING_COMPLETED`：是。**
- **`parking_completed` 实际值：`true`。**
- **是否存在未满足条件：无。** 30 项 verifier checks 全部 true；
  Gate reasons 为空。
- **是否可以进入 CAP-08：** 本阶段领域完成条件已满足，可以进入 CAP-08
  的规划/评审；但必须保留上述限制（仅仿真、稀疏障碍物、离散稳定性、
  单执行器）。按本次指令，完成 CAP-07B-06 后停止，不自行启动 CAP-08。
