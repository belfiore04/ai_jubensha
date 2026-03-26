import type { Character, StyleCard } from "./types";

/* ── 7 styles ─────────────────────────────────────── */

export const STYLES: StyleCard[] = [
  {
    value: "detective",
    label: "正统侦探",
    emoji: "🔍",
    desc: "经典推理，抽丝剥茧还原真相",
  },
  {
    value: "drama",
    label: "戏剧侦探",
    emoji: "🎭",
    desc: "笑中带泪，荒诞不经的破案之旅",
  },
  {
    value: "discover",
    label: "寻迹侦探",
    emoji: "🗺️",
    desc: "探索未知，追寻隐藏线索的冒险",
  },
  {
    value: "destiny",
    label: "命运侦探",
    emoji: "💫",
    desc: "宿命交织，冥冥之中自有安排",
  },
  {
    value: "dream",
    label: "幻梦侦探",
    emoji: "🌙",
    desc: "虚实交错，梦境与现实的边界",
  },
  {
    value: "dimension",
    label: "赛博侦探",
    emoji: "🤖",
    desc: "科技加持，数据洪流中寻找真相",
  },
  {
    value: "death",
    label: "幽冥侦探",
    emoji: "💀",
    desc: "阴森诡谲，与亡者对话的禁忌",
  },
];

/* ── 4 fixed platform characters ─────────────────── */

export const PLATFORM_CHARACTERS: Character[] = [
  {
    id: "char-zhangshan",
    name: "张山",
    avatar: "",
    personality: "退伍军人出身的厨师，豪爽硬朗，有强烈的保护欲与求胜心，是团队里最可靠的物理担当",
    description: "退伍老兵/厨师",
  },
  {
    id: "char-kue",
    name: "酷鹅",
    avatar: "",
    personality: "穿着得体、礼貌周到但精神状态随时炸裂的毒舌担当，说话简短犀利，擅长阴阳怪气和高端嘲讽",
    description: "毒舌南极监护人",
  },
  {
    id: "char-huyifei",
    name: "胡一菲",
    avatar: "",
    personality: "彪悍的大学老师，身体是女人性格是半个男人，非常要强要面子，嘴上凶狠但内心有柔软的一面",
    description: "彪悍女教师",
  },
  {
    id: "char-bbbb",
    name: "豆几",
    avatar: "",
    personality: "18岁男团爱豆，幽默搞怪抽象，看着花心其实内心中二单纯，说话直白口语化，擅长调情逗人",
    description: "搞怪男团爱豆",
  },
];

/* ── Avatar color palette (since no real images) ──── */

export const AVATAR_COLORS: Record<string, string> = {
  "char-zhangshan": "#f97316",
  "char-kue": "#60a5fa",
  "char-huyifei": "#e879f9",
  "char-bbbb": "#facc15",
  dm: "#a78bfa",
};

export function getAvatarColor(id: string): string {
  return AVATAR_COLORS[id] ?? "#4ade80";
}

export function getInitial(name: string): string {
  return name.charAt(0);
}
