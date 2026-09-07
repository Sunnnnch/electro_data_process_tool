# ElectroChem 图标候选方案

2026-09-08，使用内置 image_gen 工具生成。用户已选定 **D · 智能数据** 作为 ElectroChem 正式图标；其余方案保留用于设计记录。

更多风格见[第二轮 E–J 方案](round-2/README.md)。

| 编号 | 方向 | 文件 | 说明 |
| --- | --- | --- | --- |
| A | 伏安曲线 | [A-voltammetry.png](A-voltammetry.png) | 突出电化学曲线特征，适合强调专业分析。 |
| B | 电极与液滴 | [B-electrodes.png](B-electrodes.png) | 强调电极与液相实验，实验室辨识度直观。 |
| C | EC 字母融合 | [C-ec-monogram.png](C-ec-monogram.png) | 对应 ElectroChem 品牌，适合长期使用的主图标。 |
| D | 智能数据 | [D-intelligent-data.png](D-intelligent-data.png) | 突出数据解释与智能分析，风格偏通用分析工具。 |

正式资源保留 D 原 PNG 的全部画面，只通过 .NET 转换为包含 16/20/24/32/40/48/64/128/256 像素的 ICO。资源位于 `src/electrochem_v6/desktop/assets`；运行 `packaging/build_icon.ps1` 可复现生成及验证。图像生成原图保留在 Codex generated_images 目录；本目录保存四份未编辑的副本。

## 最终提示词

### A · 伏安曲线

```text
Use case: logo-brand. Create ONE original premium Windows application icon concept for ElectroChem, an electrochemical data analysis desktop app. Square 1024x1024 composition. A large rounded-square tile occupies about 88% of the canvas, centered on a plain very light cool gray background. Deep teal tile with a restrained smooth emerald illumination, nearly flat finish. The sole central symbol is a bold, elegant white continuous cyclic-voltammetry inspired loop with one rounded upper peak and one opposing lower peak, simplified to a confident recognizable glyph; an understated mint dot at one endpoint suggests a measured data sample. Scientific precision and calm professional research software. Symbol centered with generous internal padding, strong silhouette at 32 pixels, uniform thick strokes and rounded terminals. Front-on orthographic, crisp vector-like contours. No axes, no chart grid, no lab glassware, no heartbeat or ECG zigzag, no text, no letters, no caption, no watermark, no mockup device, no dramatic 3D extrusion. This is a standalone icon, not a presentation board.
```

### B · 电极与液滴

```text
Use case: logo-brand. Create ONE original premium Windows application icon concept for ElectroChem, an electrochemical data analysis desktop app. Square 1024x1024 composition. A large rounded-square tile occupies about 88% of the canvas, centered on a plain very light cool gray background. Rich cobalt blue tile with a subtle navy gradient, matte nearly flat finish. A single bold white droplet silhouette is cleverly integrated with two simple vertical electrode bars extending into it; a small cyan gap between the bars evokes electrochemical measurement. The electrode and droplet form one compact unified geometric mark, not an illustrated laboratory scene. Clean contemporary scientific identity, restrained and trustworthy. Front-on orthographic, crisp vector-like contours, generous internal margins, clearly legible at 32 pixels. No small bubbles, no fine circuitry, no battery symbol, no lightning bolt, no text, no letters, no caption, no watermark, no mockup device, no dramatic 3D extrusion. This is a standalone icon, not a presentation board.
```

### C · EC 字母融合

```text
Use case: logo-brand. Create ONE original premium Windows application icon concept for ElectroChem, an electrochemical data analysis desktop app. Square 1024x1024 composition. A large rounded-square tile occupies about 88% of the canvas, centered on a plain very light cool gray background. Deep midnight navy tile, smooth matte finish with extremely subtle teal glow. The central symbol is an original custom geometric monogram fusing the letters E and C into ONE bold compact continuous mark. E in warm white, C in seafoam mint, two visibly interlocking shapes, balanced generous negative space. Not ordinary typed text: a carefully drawn rounded geometric symbol that reads EC upon inspection, distinctive at small sizes. Quiet sophisticated desktop productivity software aesthetic with a scientific character. Front-on orthographic, crisp vector-like contours, consistent thick strokes, ample internal padding. No additional text or captions, no other letters, no chart, no molecular model, no complex gradients, no watermark, no mockup device, no dramatic 3D extrusion. This is a standalone icon, not a presentation board.
```

### D · 智能数据

```text
Use case: logo-brand. Create ONE original premium Windows application icon concept for ElectroChem, an electrochemical data analysis desktop app. Square 1024x1024 composition. A large rounded-square tile occupies about 88% of the canvas, centered on a plain very light cool gray background. Restrained indigo-to-deep-blue tile, nearly flat luminous finish. Central unified bold white symbol: an open softly rounded hexagonal scientific frame containing a smooth rising measurement curve, with one small cyan four-point sparkle precisely integrated at the upper-right terminal. Convey intelligent interpretation of experimental data; the sparkle is subordinate to the clear data-curve silhouette. Original, polished, friendly professional research tool. Front-on orthographic, crisp vector-like contours, thick consistent strokes, generous internal padding, recognizable at 32 pixels. No tiny dots, no atom orbital, no robot, no brain, no letters, no text, no captions, no watermark, no mockup device, no dramatic 3D extrusion. This is a standalone icon, not a presentation board.
```
