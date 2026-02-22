"""山西地电用电查询 - 传感器实体"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_CONS_NO
from .coordinator import SxgjdlDataCoordinator

_LOGGER = logging.getLogger(__name__)

UNIT_YUAN = "元"
UNIT_KWH = UnitOfEnergy.KILO_WATT_HOUR

MONTH_NAMES = {
    1: "一月", 2: "二月", 3: "三月", 4: "四月",
    5: "五月", 6: "六月", 7: "七月", 8: "八月",
    9: "九月", 10: "十月", 11: "十一月", 12: "十二月",
}


@dataclass(frozen=True)
class SxgjdlSensorEntityDescription(SensorEntityDescription):
    data_key: str = ""
    extra_attrs_keys: list = field(default_factory=list)


# ------------------------------------------------------------------ #
#  固定传感器描述（不含月度历史）                                      #
# ------------------------------------------------------------------ #
FIXED_SENSOR_DESCRIPTIONS: tuple[SxgjdlSensorEntityDescription, ...] = (
    SxgjdlSensorEntityDescription(
        key="prepay_bal", data_key="prepay_bal", name="预付余额",
        native_unit_of_measurement=UNIT_YUAN,
        state_class=SensorStateClass.TOTAL, icon="mdi:cash",
    ),
    SxgjdlSensorEntityDescription(
        key="rcv_amt_total", data_key="rcv_amt_total", name="应收电费",
        native_unit_of_measurement=UNIT_YUAN,
        state_class=SensorStateClass.TOTAL, icon="mdi:cash-clock",
    ),
    SxgjdlSensorEntityDescription(
        key="unit_price", data_key="unit_price", name="当前电价",
        native_unit_of_measurement="元/kWh",
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:currency-cny",
        extra_attrs_keys=["price_name"],
    ),
    SxgjdlSensorEntityDescription(
        key="today_usage", data_key="today_usage", name="昨日用电量",
        native_unit_of_measurement=UNIT_KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:lightning-bolt",
    ),
    SxgjdlSensorEntityDescription(
        key="today_amt", data_key="today_amt", name="昨日电费",
        native_unit_of_measurement=UNIT_YUAN,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:cash-fast",
    ),

    SxgjdlSensorEntityDescription(
        key="month_esti_usage", data_key="month_esti_usage", name="本月预估用电量",
        native_unit_of_measurement=UNIT_KWH,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:chart-line",
    ),
    SxgjdlSensorEntityDescription(
        key="month_esti_amt", data_key="month_esti_amt", name="本月预估电费",
        native_unit_of_measurement=UNIT_YUAN,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:chart-areaspline",
    ),
    SxgjdlSensorEntityDescription(
        key="last_month_usage", data_key="last_month_usage", name="上月用电量",
        native_unit_of_measurement=UNIT_KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL, icon="mdi:history",
        extra_attrs_keys=["latest_bill_ym", "latest_bill_amt", "latest_bill_pq"],
    ),
    SxgjdlSensorEntityDescription(
        key="last_month_amt", data_key="last_month_amt", name="上月电费",
        native_unit_of_measurement=UNIT_YUAN,
        state_class=SensorStateClass.TOTAL, icon="mdi:receipt-text",
        extra_attrs_keys=["latest_bill_ym", "latest_bill_pq"],
    ),
    SxgjdlSensorEntityDescription(
        key="year_total_usage", data_key="year_total_usage", name="本年用电量",
        native_unit_of_measurement=UNIT_KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:calendar-year",
    ),
    SxgjdlSensorEntityDescription(
        key="year_total_amt", data_key="year_total_amt", name="本年电费",
        native_unit_of_measurement=UNIT_YUAN,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:finance",
    ),

)


# ------------------------------------------------------------------ #
#  async_setup_entry：固定传感器 + 动态年度月度传感器                  #
# ------------------------------------------------------------------ #
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SxgjdlDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    cons_no = entry.data[CONF_CONS_NO]

    # 已注册过的年份，避免跨年重复注册
    registered_years: set[int] = set()

    entities: list[SensorEntity] = []

    # 1. 固定传感器
    for desc in FIXED_SENSOR_DESCRIPTIONS:
        entities.append(SxgjdlSensor(coordinator, desc, cons_no, entry))

    # 2. 首次注册当前年度的月度传感器
    current_year = datetime.now().year
    entities.extend(_build_yearly_entities(coordinator, cons_no, entry, current_year))
    registered_years.add(current_year)

    # 3. 年度汇总传感器（state = 年累计，attributes = 各月明细）
    entities.append(SxgjdlYearlySummarySensor(coordinator, cons_no, entry))

    async_add_entities(entities)

    # 4. 监听 coordinator 更新，跨年时动态添加新年度传感器
    async def _check_new_year(_):
        year = datetime.now().year
        if year not in registered_years:
            _LOGGER.info("检测到新年份 %d，自动注册月度传感器", year)
            new_entities = _build_yearly_entities(coordinator, cons_no, entry, year)
            async_add_entities(new_entities)
            registered_years.add(year)

    coordinator.async_add_listener(_check_new_year)


def _build_yearly_entities(
    coordinator: SxgjdlDataCoordinator,
    cons_no: str,
    entry: ConfigEntry,
    year: int,
) -> list[SensorEntity]:
    """为指定年份生成 24 个月度传感器（12个用电量 + 12个电费）"""
    entities: list[SensorEntity] = []
    for m in range(1, 13):
        entities.append(SxgjdlMonthlyUsageSensor(coordinator, cons_no, entry, year, m))
        entities.append(SxgjdlMonthlyAmtSensor(coordinator, cons_no, entry, year, m))
    return entities


# ------------------------------------------------------------------ #
#  通用固定传感器                                                       #
# ------------------------------------------------------------------ #
class SxgjdlSensor(CoordinatorEntity[SxgjdlDataCoordinator], SensorEntity):
    entity_description: SxgjdlSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, description, cons_no, entry):
        super().__init__(coordinator)
        self.entity_description = description
        self._cons_no = cons_no
        self._entry = entry
        self._attr_unique_id = f"{cons_no}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._cons_no)

    @property
    def available(self) -> bool:
        # 有缓存数据就视为可用，不显示"未知"
        return self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {}
        for k in self.entity_description.extra_attrs_keys:
            if k in data:
                attrs[k] = data[k]
        attrs.update(_common_attrs(data))
        return attrs


# ------------------------------------------------------------------ #
#  月度用电量传感器（带年份）                                           #
# ------------------------------------------------------------------ #
class SxgjdlMonthlyUsageSensor(CoordinatorEntity[SxgjdlDataCoordinator], SensorEntity):
    """某年某月用电量，例如：2026年一月用电量"""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coordinator, cons_no, entry, year: int, month: int):
        super().__init__(coordinator)
        self._cons_no = cons_no
        self._entry = entry
        self._year = year
        self._month = month
        self._data_key = f"monthly_usage_{month:02d}"
        self._attr_unique_id = f"{cons_no}_monthly_usage_{year}_{month:02d}"
        self._attr_name = f"{year}年{MONTH_NAMES[month]}用电量"
        self._attr_native_unit_of_measurement = UNIT_KWH

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._cons_no)

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        if data.get("current_year") == self._year or datetime.now().year == self._year:
            return data.get(self._data_key)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs = {
            "年份": self._year,
            "月份": self._month,
            "月份名称": MONTH_NAMES[self._month],
        }
        attrs.update(_common_attrs(data))
        return attrs


# ------------------------------------------------------------------ #
#  月度电费传感器（带年份）                                             #
# ------------------------------------------------------------------ #
class SxgjdlMonthlyAmtSensor(CoordinatorEntity[SxgjdlDataCoordinator], SensorEntity):
    """某年某月电费，例如：2026年一月电费"""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator, cons_no, entry, year: int, month: int):
        super().__init__(coordinator)
        self._cons_no = cons_no
        self._entry = entry
        self._year = year
        self._month = month
        self._data_key = f"monthly_amt_{month:02d}"
        self._attr_unique_id = f"{cons_no}_monthly_amt_{year}_{month:02d}"
        self._attr_name = f"{year}年{MONTH_NAMES[month]}电费"
        self._attr_native_unit_of_measurement = UNIT_YUAN

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._cons_no)

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        if data.get("current_year") == self._year or datetime.now().year == self._year:
            return data.get(self._data_key)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs = {
            "年份": self._year,
            "月份": self._month,
            "月份名称": MONTH_NAMES[self._month],
        }
        attrs.update(_common_attrs(data))
        return attrs


# ------------------------------------------------------------------ #
#  年度汇总传感器                                                       #
# ------------------------------------------------------------------ #
class SxgjdlYearlySummarySensor(CoordinatorEntity[SxgjdlDataCoordinator], SensorEntity):
    """年度汇总：state = 本年累计用电量，attributes = 各月明细"""

    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-bar"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UNIT_KWH

    def __init__(self, coordinator, cons_no, entry):
        super().__init__(coordinator)
        self._cons_no = cons_no
        self._entry = entry
        self._attr_unique_id = f"{cons_no}_yearly_monthly_detail"
        self._attr_name = "年度各月用电明细"

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.coordinator, self._cons_no)

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        return data.get("year_total_usage")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        summary = data.get("monthly_summary", {})
        year = summary.get("year", datetime.now().year)
        attrs: dict[str, Any] = {
            "年份": year,
            "年累计电费(元)": data.get("year_total_amt", 0.0),
        }
        for m_data in summary.get("months", []):
            name = m_data.get("name", "")
            if name:
                attrs[f"{year}年{name}用电量(kWh)"] = m_data.get("usage_kwh", 0)
                attrs[f"{year}年{name}电费(元)"] = m_data.get("amount_yuan", 0.0)
        attrs.update(_common_attrs(data))
        return attrs


# ------------------------------------------------------------------ #
#  公共工具函数                                                         #
# ------------------------------------------------------------------ #
def _device_info(coordinator: SxgjdlDataCoordinator, cons_no: str) -> DeviceInfo:
    data = coordinator.data or {}
    cons_name = data.get("cons_name", "")
    elec_addr = data.get("elec_addr", "")
    return DeviceInfo(
        identifiers={(DOMAIN, cons_no)},
        name=f"山西地电_{cons_no}",  # 设备名用户号，简洁明了
        manufacturer="山西省地方电力（集团）有限公司",
        model=cons_name or f"户号{cons_no}",  # 用户名放在 model
        sw_version="1.0.4",
        configuration_url="http://ddwxyw.sxgjdl.com",
        suggested_area=elec_addr or "电力",
    )


def _common_attrs(data: dict) -> dict[str, Any]:
    attrs = {}
    if "cons_name" in data:
        attrs["户名"] = data["cons_name"]
    if "elec_addr" in data:
        attrs["用电地址"] = data["elec_addr"]
    if "org_name" in data:
        attrs["供电所"] = data["org_name"]
    if "last_mr_date" in data:
        attrs["上次抄表日期"] = data["last_mr_date"]
    # 维护期间使用缓存时显示提示
    if data.get("_using_cache"):
        attrs["⚠️ 数据来源"] = "缓存（服务器维护中）"
    if "_last_updated" in data:
        attrs["最后成功更新"] = data["_last_updated"]
    return attrs
