import { ref, watch } from "vue";

// Словари. Ключи общие, en обязан содержать те же ключи, что ru (проверяет TypeScript).
const ru = {
  "app.title": "PlantControl",
  "app.version": "Версия {version}",
  "app.author": "Автор: Egor",
  "app.language": "Язык",
  "app.theme": "Тема",
  "theme.auto": "Как в системе",
  "theme.light": "Светлая",
  "theme.dark": "Тёмная",

  "unit.ml": "мл",
  "unit.l": "л",
  "unit.mm": "мм",
  "unit.m": "м",
  "unit.s": "с",
  "unit.ml_s": "мл/с",
  "unit.l_h": "л/ч",
  "unit.percent": "%",

  "list.add": "Добавить поливальную машину",
  "list.ha_connected": "HA подключен",
  "list.ha_status": "HA: {status}",
  "list.empty": "Поливальных машин пока нет.",
  "list.empty_hint":
    "Добавьте первую: укажите бак, насос из Home Assistant и трубку до растения.",

  "card.watering": "поливает",
  "card.pump_on": "насос работает",
  "card.pump_off": "насос выключен",
  "card.pump_unknown": "насос: неизвестно",
  "card.valves": "Клапаны:",
  "card.last": "Последний полив:",
  "card.ok": "ok",
  "card.error": "ошибка",
  "card.water": "Полить",
  "card.tank": "Бак",
  "card.settings": "Настроить",
  "card.stop": "Стоп",
  "gauge.available": "Доступно",
  "gauge.of": "из {capacity}, запас {reserve}",
  "gauge.level": "Уровень {level} мм",

  "water.title": "Полить: {name}",
  "water.plant": "Растение",
  "water.dose": "Доза",
  "water.duration": "Время работы насоса",
  "water.pumped": "Насос прокачает",
  "water.consumed": "Уйдёт из бака",
  "water.head": "Высота подъёма в начале / в конце",
  "water.flow": "Расход в начале / в конце",
  "water.calculate": "Рассчитать",
  "water.start": "Полить",

  "tank.title": "Бак: {name}",
  "tank.now": "Сейчас по расчёту {volume} из {capacity}.",
  "tank.full": "Залил до полного",
  "tank.set": "Или укажите, сколько воды в баке сейчас",
  "tank.save": "Сохранить объём",

  "form.new": "Новая поливальная машина",
  "form.machine": "Поливальная машина",
  "form.back": "Назад",
  "form.loading": "Загрузка...",
  "form.create": "Создать",
  "form.save": "Сохранить",
  "form.cancel": "Отмена",
  "form.delete": "Удалить",
  "form.delete_confirm": "Удалить поливальную машину «{name}»?",

  "general.title": "Общее",
  "general.desc": "Как называется машина и как она устроена.",
  "tank.desc": "Откуда насос берёт воду. От бака зависит, сколько поливов хватит и как меняется напор.",
  "pump.desc": "Какой сущностью в Home Assistant включается насос и сколько воды он даёт.",
  "tube.desc": "Путь воды от насоса до растения. Нужен, чтобы учесть воду в трубке и высоту подъёма.",
  "collector.desc": "Общая трубка от бака до коллектора и паузы вокруг работы насоса.",
  "plants.desc": "У каждого растения свой клапан и своя трубка от коллектора.",
  "card.plant": "Растение",
  "card.no_plant": "растение не указано",
  "card.actions": "Действия",
  "general.name": "Название машины",
  "general.name_placeholder": "Полив на подоконнике",
  "general.plant": "Растение",
  "general.plant_placeholder": "Фикус",
  "general.type": "Тип",
  "type.direct": "Без коллектора",
  "type.collector": "С коллектором",
  "type.direct_hint":
    "Один насос поливает одно растение по одной трубке. Когда насос выключается, трубка пустеет.",
  "type.collector_hint":
    "Один насос и коллектор с клапанами на несколько растений. Машина открывает клапан нужного растения и включает насос. Трубка от бака до коллектора остаётся заполненной.",

  "tank.section": "Бак",
  "tank.mode": "Как задать бак",
  "tank.mode.measured": "По замеру: объём и высота воды",
  "tank.mode.shape": "По форме и размерам",
  "tank.mode_hint_measured":
    "Подходит для любой ёмкости, даже неровной: банки, ведра, канистры. Нужны два замера.",
  "tank.mode_hint_shape": "Для бака правильной формы, когда известны его размеры.",
  "tank.volume": "Объём до линии налива",
  "tank.volume_hint":
    "Налейте воду мерной кружкой до уровня, до которого обычно заливаете бак, и сложите объём.",
  "tank.height": "Высота воды при полном баке",
  "tank.height_hint": "Линейкой от дна до поверхности воды, когда бак налит как обычно.",
  "tank.shape": "Форма",
  "tank.shape.cylinder": "Цилиндр",
  "tank.shape.rectangular": "Прямоугольный",
  "tank.orientation": "Ориентация",
  "tank.orientation.vertical": "Вертикально (стоит)",
  "tank.orientation.horizontal": "Горизонтально (лежит)",
  "tank.diameter": "Внутренний диаметр",
  "tank.diameter_hint": "Изнутри, по дну или по середине высоты.",
  "tank.cyl_height": "Высота до линии налива",
  "tank.cyl_height_hint": "От дна до уровня, до которого наливаете воду.",
  "tank.length": "Длина",
  "tank.width": "Ширина",
  "tank.depth": "Глубина",
  "tank.rect_height": "Высота до линии налива",
  "tank.reserve": "Запас под насосом",
  "tank.reserve_hint":
    "Сколько воды остаётся внизу, когда погружной насос уже не может её забрать. Ей не поливают.",

  "pump.section": "Насос",
  "pump.entity": "Сущность в Home Assistant",
  "pump.entity_hint": "Выключатель, которым включается насос: switch.* или input_boolean.*",
  "pump.entities_unavailable":
    "Список сущностей из Home Assistant недоступен ({error}), введите id вручную.",
  "pump.model": "Как задать расход",
  "pump.model.constant": "Постоянный расход",
  "pump.model.linear": "По характеристикам производителя",
  "pump.model.table": "По своим замерам",
  "pump.model_hint.constant":
    "Одно число: сколько насос наливает за секунду. Высота подъёма не учитывается. Годится для коротких трубок и небольшой высоты.",
  "pump.model_hint.linear":
    "Два числа с коробки или страницы насоса. Чем выше надо поднять воду, тем меньше расход.",
  "pump.model_hint.table":
    "Несколько замеров на разной высоте, самый точный вариант. По строке: высота подъёма в мм и расход в мл/с.",
  "pump.flow": "Расход",
  "pump.flow_hint":
    "Включите насос на 10 с, соберите воду в мерный стакан и разделите объём на 10.",
  "pump.qmax": "Максимальный расход (Qmax)",
  "pump.qmax_hint": "Расход без подъёма воды, обычно в л/ч.",
  "pump.hmax": "Максимальная высота подъёма (Hmax)",
  "pump.hmax_hint": "Высота, на которой вода уже не идёт, обычно в метрах.",
  "pump.points": "Замеры: высота подъёма (мм) и расход (мл/с), по строке",
  "pump.max_runtime": "Предел работы за один полив",
  "pump.max_runtime_hint":
    "Защита: насос не проработает дольше за один раз. Дозу, которой нужно больше времени, машина не примет.",
  "pump.cooldown": "Пауза между поливами",
  "pump.cooldown_hint": "Минимальный отдых насоса между включениями. 0 - без паузы.",

  "tube.section": "Трубка",
  "tube.supply_section": "Коллектор",
  "tube.length": "Длина трубки",
  "tube.length_hint": "От насоса до конца трубки у растения.",
  "tube.supply_length": "Длина трубки от бака до коллектора",
  "tube.plant_length": "Длина трубки от клапана до растения",
  "tube.diameter": "Внутренний диаметр трубки",
  "tube.diameter_hint":
    "Диаметр отверстия, а не трубки снаружи. Для силиконовой трубки 4x6 это 4 мм.",
  "tube.outlet": "Высота конца трубки над дном бака",
  "tube.outlet_hint":
    "От дна бака до места, где вода выходит у растения. Если выход ниже дна - отрицательное число.",
  "tube.back": "Сколько воды из трубки стекает обратно в бак",
  "tube.back_hint":
    "Когда насос выключается, вода из трубки стекает: часть назад в бак через насос, часть в растение. Укажите долю объёма трубки, которая уходит в бак. 0% - вся в растение, 100% - вся в бак.",
  "tube.correction": "Поправочный коэффициент",
  "tube.correction_hint":
    "Уточняет расчёт по факту. Закажите дозу и измерьте, сколько вылилось: заказали 100 мл, получили 90 - поставьте 0,9. 1 - без поправки.",
  "tube.lead": "Пауза: клапан открыт, насос ещё нет",
  "tube.lead_hint": "Даёт клапану открыться до того, как насос даст давление.",
  "tube.lag": "Пауза: насос выключен, клапан ещё открыт",
  "tube.lag_hint": "Даёт давлению упасть до того, как клапан закроется.",

  "plants.section": "Растения",
  "plants.name": "Растение",
  "plants.code": "Код",
  "plants.code_hint": "Латиница, цифры, - и _. Нужен для API.",
  "plants.valve": "Сущность клапана в Home Assistant",
  "plants.add": "Добавить растение",
  "plants.remove": "Убрать",

  "advanced.title": "Дополнительно",
  "advanced.head": "Как учитывать падение уровня во время полива",
  "advanced.head_intro":
    "Пока насос работает, вода в баке опускается, насосу приходится поднимать её выше, и расход падает. Для небольших доз разница почти не видна.",
  "head.start": "По уровню в начале полива",
  "head.mid": "По уровню на середине дозы",
  "head.stepwise": "Пошагово",
  "head_hint.start": "Считается проще всего, время выходит чуть меньше реального.",
  "head_hint.mid": "Рекомендуется: почти не отличается от точного расчёта.",
  "head_hint.stepwise":
    "Доза делится на 20 шагов, у каждого свой уровень. Самый точный, заметен на больших дозах в маленьком баке.",

  "errors.MachineBusyError": "Машина уже поливает",
  "errors.NotEnoughWaterError": "В баке мало воды",
  "errors.TankOverflowError": "Столько не поместится в бак",
  "errors.PumpCoolingDownError": "Насос ещё отдыхает после прошлого полива",
  "errors.PumpAlreadyRunningError": "Насос уже работает",
  "errors.PumpRuntimeExceededError": "Доза не укладывается в предел работы насоса за один полив",
  "errors.PumpCannotDeliverError": "Насос не поднимет воду на такую высоту",
  "errors.PumpStateUnknownError": "Состояние насоса неизвестно. Нажмите Стоп",
  "errors.CollectorStateUnknownError": "Состояние клапанов неизвестно. Нажмите Стоп",
  "errors.AnotherValveOpenError": "Открыт другой клапан",
  "errors.PumpControlError": "Не удалось переключить насос",
  "errors.ValveControlError": "Не удалось переключить клапан",
  "errors.HomeAssistantUnavailableError": "Нет связи с Home Assistant",
  "errors.UnknownMachineError": "Машина не найдена",
  "errors.status": "Ошибка {status}",
};

export type MessageKey = keyof typeof ru;

const en: Record<MessageKey, string> = {
  "app.title": "PlantControl",
  "app.version": "Version {version}",
  "app.author": "Author: Egor",
  "app.language": "Language",
  "app.theme": "Theme",
  "theme.auto": "System",
  "theme.light": "Light",
  "theme.dark": "Dark",

  "unit.ml": "ml",
  "unit.l": "L",
  "unit.mm": "mm",
  "unit.m": "m",
  "unit.s": "s",
  "unit.ml_s": "ml/s",
  "unit.l_h": "L/h",
  "unit.percent": "%",

  "list.add": "Add watering machine",
  "list.ha_connected": "HA connected",
  "list.ha_status": "HA: {status}",
  "list.empty": "No watering machines yet.",
  "list.empty_hint":
    "Add the first one: describe the tank, the pump entity from Home Assistant and the tube to the plant.",

  "card.watering": "watering",
  "card.pump_on": "pump on",
  "card.pump_off": "pump off",
  "card.pump_unknown": "pump: unknown",
  "card.valves": "Valves:",
  "card.last": "Last watering:",
  "card.ok": "ok",
  "card.error": "error",
  "card.water": "Water",
  "card.tank": "Tank",
  "card.settings": "Settings",
  "card.stop": "Stop",
  "gauge.available": "Available",
  "gauge.of": "of {capacity}, reserve {reserve}",
  "gauge.level": "Level {level} mm",

  "water.title": "Water: {name}",
  "water.plant": "Plant",
  "water.dose": "Dose",
  "water.duration": "Pump run time",
  "water.pumped": "Pump will move",
  "water.consumed": "Taken from the tank",
  "water.head": "Lift height at start / end",
  "water.flow": "Flow at start / end",
  "water.calculate": "Calculate",
  "water.start": "Water",

  "tank.title": "Tank: {name}",
  "tank.now": "Estimated {volume} of {capacity} right now.",
  "tank.full": "Filled it up",
  "tank.set": "Or enter how much water is in the tank now",
  "tank.save": "Save volume",

  "form.new": "New watering machine",
  "form.machine": "Watering machine",
  "form.back": "Back",
  "form.loading": "Loading...",
  "form.create": "Create",
  "form.save": "Save",
  "form.cancel": "Cancel",
  "form.delete": "Delete",
  "form.delete_confirm": "Delete watering machine \"{name}\"?",

  "general.title": "General",
  "general.desc": "What the machine is called and how it is built.",
  "tank.desc": "Where the pump takes water from. The tank defines how many waterings you get and how the lift changes.",
  "pump.desc": "Which Home Assistant entity powers the pump and how much water it delivers.",
  "tube.desc": "The way from the pump to the plant. Needed to account for water in the tube and the lift height.",
  "collector.desc": "The shared tube from the tank to the collector and the pauses around the pump run.",
  "plants.desc": "Each plant has its own valve and its own tube from the collector.",
  "card.plant": "Plant",
  "card.no_plant": "no plant set",
  "card.actions": "Actions",
  "general.name": "Machine name",
  "general.name_placeholder": "Windowsill watering",
  "general.plant": "Plant",
  "general.plant_placeholder": "Ficus",
  "general.type": "Type",
  "type.direct": "Without collector",
  "type.collector": "With collector",
  "type.direct_hint":
    "One pump waters one plant through one tube. When the pump stops, the tube drains.",
  "type.collector_hint":
    "One pump and a collector with valves for several plants. The machine opens the valve of the chosen plant and starts the pump. The tube from the tank to the collector stays filled.",

  "tank.section": "Tank",
  "tank.mode": "How to describe the tank",
  "tank.mode.measured": "Measured: volume and water height",
  "tank.mode.shape": "By shape and size",
  "tank.mode_hint_measured":
    "Works for any container, even an irregular one: a jar, a bucket, a canister. Needs two measurements.",
  "tank.mode_hint_shape": "For a tank of regular shape with known dimensions.",
  "tank.volume": "Volume up to the fill line",
  "tank.volume_hint":
    "Pour water with a measuring cup up to the level you usually fill to and add up the volume.",
  "tank.height": "Water height when full",
  "tank.height_hint": "With a ruler from the bottom to the water surface when the tank is filled as usual.",
  "tank.shape": "Shape",
  "tank.shape.cylinder": "Cylinder",
  "tank.shape.rectangular": "Rectangular",
  "tank.orientation": "Orientation",
  "tank.orientation.vertical": "Vertical (standing)",
  "tank.orientation.horizontal": "Horizontal (lying)",
  "tank.diameter": "Inner diameter",
  "tank.diameter_hint": "Inside, at the bottom or at mid height.",
  "tank.cyl_height": "Height up to the fill line",
  "tank.cyl_height_hint": "From the bottom to the level you fill water to.",
  "tank.length": "Length",
  "tank.width": "Width",
  "tank.depth": "Depth",
  "tank.rect_height": "Height up to the fill line",
  "tank.reserve": "Reserve under the pump",
  "tank.reserve_hint":
    "Water left at the bottom that a submersible pump can no longer take. It is not used for watering.",

  "pump.section": "Pump",
  "pump.entity": "Home Assistant entity",
  "pump.entity_hint": "The switch that powers the pump: switch.* or input_boolean.*",
  "pump.entities_unavailable":
    "Entity list from Home Assistant is unavailable ({error}), type the id manually.",
  "pump.model": "How to describe the flow",
  "pump.model.constant": "Constant flow",
  "pump.model.linear": "Manufacturer specs",
  "pump.model.table": "My own measurements",
  "pump.model_hint.constant":
    "One number: how much the pump delivers per second. Lift height is ignored. Fine for short tubes and small heights.",
  "pump.model_hint.linear":
    "Two numbers from the box or the product page. The higher the water has to go, the lower the flow.",
  "pump.model_hint.table":
    "Several measurements at different heights, the most accurate option. One per line: lift height in mm and flow in ml/s.",
  "pump.flow": "Flow",
  "pump.flow_hint":
    "Run the pump for 10 s, collect the water in a measuring cup and divide the volume by 10.",
  "pump.qmax": "Maximum flow (Qmax)",
  "pump.qmax_hint": "Flow with no lift, usually in L/h.",
  "pump.hmax": "Maximum lift height (Hmax)",
  "pump.hmax_hint": "Height at which water stops flowing, usually in meters.",
  "pump.points": "Measurements: lift height (mm) and flow (ml/s), one per line",
  "pump.max_runtime": "Maximum run time per watering",
  "pump.max_runtime_hint":
    "Safety limit: the pump never runs longer in one go. A dose that needs more time is rejected.",
  "pump.cooldown": "Pause between waterings",
  "pump.cooldown_hint": "Minimum rest for the pump between runs. 0 means no pause.",

  "tube.section": "Tube",
  "tube.supply_section": "Collector",
  "tube.length": "Tube length",
  "tube.length_hint": "From the pump to the tube end at the plant.",
  "tube.supply_length": "Tube length from tank to collector",
  "tube.plant_length": "Tube length from valve to plant",
  "tube.diameter": "Tube inner diameter",
  "tube.diameter_hint": "The hole, not the outside of the tube. For a 4x6 silicone tube it is 4 mm.",
  "tube.outlet": "Tube end height above the tank bottom",
  "tube.outlet_hint":
    "From the tank bottom to where water comes out at the plant. Negative if the outlet is below the bottom.",
  "tube.back": "How much water drains back into the tank",
  "tube.back_hint":
    "When the pump stops, water left in the tube drains: part back into the tank through the pump, part into the plant. Enter the share of the tube volume that returns to the tank. 0% - all into the plant, 100% - all into the tank.",
  "tube.correction": "Correction factor",
  "tube.correction_hint":
    "Adjusts the calculation to reality. Order a dose and measure what came out: ordered 100 ml, got 90 - set 0.9. 1 means no correction.",
  "tube.lead": "Pause: valve open, pump not yet",
  "tube.lead_hint": "Lets the valve open before the pump builds pressure.",
  "tube.lag": "Pause: pump off, valve still open",
  "tube.lag_hint": "Lets the pressure drop before the valve closes.",

  "plants.section": "Plants",
  "plants.name": "Plant",
  "plants.code": "Code",
  "plants.code_hint": "Latin letters, digits, - and _. Used by the API.",
  "plants.valve": "Valve entity in Home Assistant",
  "plants.add": "Add plant",
  "plants.remove": "Remove",

  "advanced.title": "Advanced",
  "advanced.head": "How to account for the level drop during watering",
  "advanced.head_intro":
    "While the pump runs, the water level drops, the pump has to lift water higher and the flow goes down. For small doses the difference is barely visible.",
  "head.start": "By the level at the start",
  "head.mid": "By the level at mid dose",
  "head.stepwise": "Step by step",
  "head_hint.start": "Simplest, the time comes out slightly shorter than real.",
  "head_hint.mid": "Recommended: almost the same as the exact calculation.",
  "head_hint.stepwise":
    "The dose is split into 20 steps, each with its own level. Most accurate, noticeable for large doses in a small tank.",

  "errors.MachineBusyError": "The machine is already watering",
  "errors.NotEnoughWaterError": "Not enough water in the tank",
  "errors.TankOverflowError": "That much will not fit into the tank",
  "errors.PumpCoolingDownError": "The pump is still resting after the last watering",
  "errors.PumpAlreadyRunningError": "The pump is already running",
  "errors.PumpRuntimeExceededError": "The dose does not fit into the pump run time limit",
  "errors.PumpCannotDeliverError": "The pump cannot lift water that high",
  "errors.PumpStateUnknownError": "Pump state is unknown. Press Stop",
  "errors.CollectorStateUnknownError": "Valve state is unknown. Press Stop",
  "errors.AnotherValveOpenError": "Another valve is open",
  "errors.PumpControlError": "Could not switch the pump",
  "errors.ValveControlError": "Could not switch the valve",
  "errors.HomeAssistantUnavailableError": "No connection to Home Assistant",
  "errors.UnknownMachineError": "Machine not found",
  "errors.status": "Error {status}",
};

export type Locale = "ru" | "en";
const MESSAGES: Record<Locale, Record<MessageKey, string>> = { ru, en };
export const LOCALES: { code: Locale; label: string }[] = [
  { code: "ru", label: "Русский" },
  { code: "en", label: "English" },
];

// localStorage может быть недоступен (приватный режим, запреты): всё в try/catch.
function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // не сохранили - не страшно, настройка действует до перезагрузки
  }
}

function initialLocale(): Locale {
  const saved = load("plant-control.locale");
  if (saved === "ru" || saved === "en") return saved;
  return navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en";
}

export const locale = ref<Locale>(initialLocale());

watch(
  locale,
  (value) => {
    store("plant-control.locale", value);
    document.documentElement.lang = value;
  },
  { immediate: true },
);

export function t(key: MessageKey, params: Record<string, string | number> = {}): string {
  let text = MESSAGES[locale.value][key] ?? key;
  for (const [name, value] of Object.entries(params)) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

export function hasMessage(key: string): key is MessageKey {
  return key in ru;
}

// --- Тема ---

export type Theme = "auto" | "light" | "dark";

function initialTheme(): Theme {
  const saved = load("plant-control.theme");
  return saved === "light" || saved === "dark" ? saved : "auto";
}

export const theme = ref<Theme>(initialTheme());

watch(
  theme,
  (value) => {
    store("plant-control.theme", value);
    if (value === "auto") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = value;
    }
  },
  { immediate: true },
);
