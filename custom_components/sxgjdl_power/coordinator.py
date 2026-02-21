"""山西地电用电查询 - 数据协调器"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SxgjdlApiClient, SxgjdlApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MONTH_NAMES = {
    1: "一月", 2: "二月", 3: "三月", 4: "四月",
    5: "五月", 6: "六月", 7: "七月", 8: "八月",
    9: "九月", 10: "十月", 11: "十一月", 12: "十二月",
}


class SxgjdlDataCoordinator(DataUpdateCoordinator):
    """统一数据更新协调器，汇总所有接口数据"""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SxgjdlApiClient,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )
        self.client = client
        # 缓存上一次成功的数据，维护期间直接返回缓存
        self._last_valid_data: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """拉取所有数据并汇总，失败时返回上次有效数据"""
        now = datetime.now()
        current_year = now.year
        current_month = now.strftime("%Y%m")
        today = now.strftime("%Y%m%d")

        result: dict[str, Any] = {}
        any_success = False

        # 1. 电费信息（余额、应收）
        try:
            fees = await self.client.get_fees()
            if fees.get("flag"):
                fee_data = fees.get("data", {})
                result["prepay_bal"] = fee_data.get("prepayBal", 0.0)
                result["rcv_amt_total"] = fee_data.get("rcvAmtTotal", 0.0)
                result["amt_total"] = fee_data.get("amtTotal", 0.0)
                result["org_name"] = fee_data.get("orgName", "")
                result["cons_name"] = fee_data.get("consName", "")
                result["elec_addr"] = fee_data.get("elecAddr", "")
                any_success = True
        except SxgjdlApiError as err:
            _LOGGER.warning("获取电费信息失败: %s", err)

        # 2. 年度月度汇总（本年）
        try:
            record = await self.client.get_record_list(current_year)
            if record.get("flag"):
                rec_data = record.get("data", {})
                record_list = rec_data.get("recordList", [])
                cons_detail = rec_data.get("consDetail", {})

                result["year_total_usage"] = cons_detail.get("maxPq", 0)
                result["year_total_amt"] = cons_detail.get("amtTotal", 0.0)
                result["cons_name"] = result.get("cons_name") or cons_detail.get("consName", "")
                result["elec_addr"] = result.get("elec_addr") or cons_detail.get("elecAddr", "")

                cur_month_num = now.month
                last_month_num = cur_month_num - 1 if cur_month_num > 1 else 12

                for rec in record_list:
                    m = rec.get("month", 0)
                    if m == cur_month_num:
                        result["month_usage"] = rec.get("thisPq", 0)
                        result["month_amt"] = rec.get("prices", 0.0)
                    elif m == last_month_num:
                        result["last_month_usage"] = rec.get("thisPq", 0)
                        result["last_month_amt"] = rec.get("prices", 0.0)

                for rec in record_list:
                    m = rec.get("month", 0)
                    if 1 <= m <= 12:
                        result[f"monthly_usage_{m:02d}"] = rec.get("thisPq", 0)
                        result[f"monthly_amt_{m:02d}"] = rec.get("prices", 0.0)

                monthly_summary = {
                    "year": current_year,
                    "months": [
                        {
                            "month": rec.get("month"),
                            "name": MONTH_NAMES.get(rec.get("month", 0), ""),
                            "usage_kwh": rec.get("thisPq", 0),
                            "amount_yuan": rec.get("prices", 0.0),
                        }
                        for rec in record_list
                        if rec.get("month", 0) > 0
                    ],
                }
                result["monthly_summary"] = monthly_summary
                result["record_list"] = record_list
                any_success = True
        except SxgjdlApiError as err:
            _LOGGER.warning("获取年度用电记录失败: %s", err)

        # 3. 月度每日用电（本月）
        try:
            days_data = await self.client.get_days_of_month(current_month)
            if days_data.get("flag"):
                daily_list = days_data.get("data", [])
                result["daily_list"] = daily_list

                # 昨日数据（服务器通常次日才上传今天的数据）
                today_entry = None
                latest_entry = None
                for entry in daily_list:
                    if entry.get("ymd") == today:
                        today_entry = entry
                    if entry.get("dayEstiPq") is not None:
                        latest_entry = entry

                active = today_entry or latest_entry
                if active:
                    # key 保持 today_* 不变（避免破坏兼容性），但传感器名称改为"昨日"
                    result["today_usage"] = active.get("dayEstiPq") or 0
                    result["today_amt"] = float(active.get("dayEstiAmt") or 0)
                    result["month_esti_usage"] = active.get("estiPq") or 0
                    result["month_esti_amt"] = float(active.get("estiAmt") or 0)
                    result["last_mr_date"] = active.get("lastMrDate", "")
                any_success = True
        except SxgjdlApiError as err:
            _LOGGER.warning("获取月度每日用电失败: %s", err)

        # 4. 今日分时数据
        try:
            day_only = await self.client.get_days_only_data(today)
            if day_only.get("flag"):
                d = day_only.get("data", {})
                result["today_total_pq"] = d.get("totalPq")
                result["today_peak_pq"] = d.get("peakPq")
                result["today_flat_pq"] = d.get("flatPq")
                result["today_valley_pq"] = d.get("valleyPq")
                result["today_day_total_pq"] = d.get("dayTotalPq")
                any_success = True
        except SxgjdlApiError as err:
            _LOGGER.warning("获取今日分时用电失败: %s", err)

        # 5. 当年账单明细
        try:
            bill = await self.client.get_list_by_year(current_year)
            bill_data = bill.get("data") or []
            if bill_data:
                latest_bill = bill_data[0]
                pay_details = latest_bill.get("payDetailList", [])
                if pay_details:
                    result["unit_price"] = float(pay_details[0].get("kwhPrc", 0))
                    result["price_name"] = pay_details[0].get("prcName", "")
                result["latest_bill_ym"] = latest_bill.get("rcvblYm", "")
                result["latest_bill_amt"] = latest_bill.get("rcvblAmt", 0.0)
                result["latest_bill_pq"] = latest_bill.get("tPq", 0)
                result["bill_list"] = bill_data
                any_success = True
        except SxgjdlApiError as err:
            _LOGGER.warning("获取账单明细失败: %s", err)

        # ------------------------------------------------------------------ #
        # 缓存逻辑：有新数据则更新缓存；全部失败则用缓存，避免传感器变"未知"  #
        # ------------------------------------------------------------------ #
        if any_success and result:
            # 用新数据更新缓存（只覆盖本次成功拿到的 key）
            self._last_valid_data.update(result)
            # 记录上次成功更新时间
            self._last_valid_data["_last_updated"] = now.strftime("%Y-%m-%d %H:%M:%S")
            _LOGGER.debug("数据更新成功，已刷新缓存")
            return dict(self._last_valid_data)

        if self._last_valid_data:
            # 全部接口失败，返回缓存数据，并打上维护标记
            _LOGGER.warning("所有接口请求失败，使用缓存数据（可能为服务器维护中）")
            cached = dict(self._last_valid_data)
            cached["_using_cache"] = True
            return cached

        # 首次启动就全部失败，才真正抛出异常
        raise UpdateFailed("所有接口均无法获取数据，请检查户号或网络连接")
