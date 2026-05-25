---
name: vault-report
description: >
  Báo cáo tổng quan các chỉ số chính của 5 Harmonix vaults từ dữ liệu.
  Load skill này khi user hỏi về vault, TVL, APY, points, price per share,
  tình hình thị trường Harmonix, hoặc muốn cập nhật số liệu DeFi.
version: 1.3.0
metadata:
  hermes:
    tags: [harmonix, defi, vault, tvl, apy, points, sqlite, finance]
    category: finance
---

# Vault Report

Báo cáo tổng quan Harmonix vaults từ SQLite database được cập nhật định kỳ.

## When to Use

Load skill này khi user đề cập đến:
- Vault Harmonix: "vault", "tvl", "apy", "tình hình vault", "số liệu vault"
- Points: "point", "điểm", "harmonix points", "kpoints", "hypurrfi"
- Tài sản: "tổng tài sản", "total assets", "hype staked", "depositors"
- Cập nhật: "cập nhật số liệu", "báo cáo", "thống kê", "tình hình", "update"
- Giá: "price per share", "risk factor", "apy 30d"

## Procedure

### Bước 1: Query SQLite database

**IMPORTANT: Chỉ đọc dữ liệu có sẵn. KHÔNG chạy collect_points.py khi chưa hỏi user.**

```bash
python3 bin/query_report.py
```

Nếu nhận lỗi "Database not found" hoặc "No data found":
1. **Hỏi user trước**: "Database chưa có data. Bạn có muốn tôi thu thập dữ liệu mới từ API không?"
2. Nếu user đồng ý, mới chạy:
   ```bash
   python3 bin/collect_points.py
   ```
3. Sau đó chạy lại `query_report.py`

### Bước 2: Format output đẹp cho Telegram

**KHÔNG relay raw output từ script.** Phải format lại theo template:

```
Dữ liệu đã được cập nhật lúc 10:14 UTC hôm nay.

Tổng quan
═══════════════════════════════════════
Total Assets:    $6,229,978
Depositors:      13,337
HYPE Staked:     $1,787,644

═══════════════════════════════════════
HIP-3 haUSDC Vault
═══════════════════════════════════════
Chain:           hyperevm
Currency:        USDC
TVL:             $220,042.55
APY 30D:         9.48%
Price/Share:     1.000992
Risk Factor:     0

═══════════════════════════════════════
HyperEVM $KHYPE Vault
═══════════════════════════════════════
Chain:           hyperevm
Currency:        KHYPE
TVL:             $1,756,698
APY 30D:         3.34%
Price/Share:     1.016924
Risk Factor:     0
Points:
  • Harmonix:    5,311,184
  • hypurrfi:    2,664,633
  • kPoints:     71,598

═══════════════════════════════════════
HyperEVM $HYPE Vault
═══════════════════════════════════════
Chain:           hyperevm
Currency:        HYPE
TVL:             $1,720,000
APY 30D:         2.98%
Price/Share:     1.035509
Risk Factor:     0
Points:
  • hypurrfi:    13,317,425
  • Harmonix:    12,030,370
  • kPoints:     27,691
  • ventuals:    8,646
  • usefelix:    7,412

[...2 vaults còn lại theo cùng format]

═══════════════════════════════════════

Phân tích:
- APY cao nhất: HIP-3 haUSDC (9.48%)
- TVL lớn nhất: HyperEVM $KHYPE ($1.76M)
```

**Format rules:**
- **Separator**: `═══════════════════════════════════════` (39 ký tự, U+2550)
- **Field alignment**: Label bên trái, value căn cột 17 (dùng spaces để align)
  - Ví dụ: `TVL:             $220,042` (13 spaces giữa `:` và `$`)
- **Vault title**: Tên vault đơn giản, không thêm emoji hay ký hiệu
- **Hiển thị theo thứ tự**: TVL giảm dần
- **Chỉ hiển thị fields có data**:
  - Chain, Currency, TVL, APY 30D, Price/Share luôn có
  - Risk Factor: hiện số (hoặc "N/A" nếu null)
  - Points: chỉ hiện nếu có points > 0, indent 2 spaces, align giá trị ở cột 17
- **Format numbers**:
  - Tiền < $1M: `$220,042.55` (2 decimal)
  - Tiền > $1M: `$1,756,698` (no decimal) hoặc `$1.76M`
  - APY: `9.48%` (2 decimal)
  - Price/Share: `1.000992` (6 decimal)
  - Points: `5,311,184` (no decimal, có comma)
- **Không dùng markdown** trong output (no bold, no italic)
- **Dòng trống** giữa summary và vaults, KHÔNG có dòng trống giữa các vault

### Bước 3: Thêm phân tích (optional)

Nếu user hỏi về so sánh, thêm:
- APY cao nhất là vault nào
- TVL lớn nhất
- Vault nào có nhiều points nhất

## Pitfalls

- **Path resolution**: Scripts tự detect PROFILE_DIR qua `__file__`. Nếu chạy từ thư mục khác hoặc gặp lỗi path, set `HARMONIX_PROFILE_DIR=/path/to/harmonix-point` trước khi chạy.
- **DB không có data**: Nếu script báo lỗi "Database not found" hoặc "No data found", chạy `collect_points.py` thủ công trước.
- **Data cũ**: DB được cập nhật mỗi 15 phút qua cron job. Nếu cần real-time, chạy `collect_points.py` trước rồi mới chạy `query_report.py`.
- **Vault không tìm thấy**: Kiểm tra slug đúng chính tả theo danh sách trên.

## Verification

Output hợp lệ khi có đủ:
- Dòng header với timestamp UTC
- Total Assets, Depositors, HYPE Staked
- 5 vault blocks với TVL, APY 30D, Price/Share
