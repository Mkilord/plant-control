// Узкий экран (телефон): подсказки и списки открываются панелью снизу.
import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

export const NARROW_QUERY = "(max-width: 600px)";

export function useNarrow(): Ref<boolean> {
  const narrow = ref(false);
  let media: MediaQueryList | null = null;
  const update = () => (narrow.value = media?.matches ?? false);
  onMounted(() => {
    media = window.matchMedia(NARROW_QUERY);
    update();
    media.addEventListener("change", update);
  });
  onBeforeUnmount(() => media?.removeEventListener("change", update));
  return narrow;
}

// Одновременно открыта одна всплывашка: открытие новой закрывает прежнюю.
let closeCurrent: (() => void) | null = null;

export function claimPopup(close: () => void): void {
  if (closeCurrent && closeCurrent !== close) closeCurrent();
  closeCurrent = close;
}

export function releasePopup(close: () => void): void {
  if (closeCurrent === close) closeCurrent = null;
}

// Место для всплывашки рядом с элементом: не ближе MARGIN к краям экрана,
// снизу от элемента, а если там тесно, сверху.
const MARGIN = 8;
const GAP = 6;

export interface PopupPlace {
  left: number;
  top: number;
  maxHeight: number;
  above: boolean;
}

export function placeNear(anchor: DOMRect, width: number, height: number): PopupPlace {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const left = Math.max(MARGIN, Math.min(anchor.left, vw - width - MARGIN));
  const below = vh - anchor.bottom - GAP - MARGIN;
  const over = anchor.top - GAP - MARGIN;
  const above = height > below && over > below;
  const maxHeight = Math.max(80, above ? over : below);
  const top = above ? Math.max(MARGIN, anchor.top - GAP - Math.min(height, maxHeight)) : anchor.bottom + GAP;
  return { left, top, maxHeight, above };
}
