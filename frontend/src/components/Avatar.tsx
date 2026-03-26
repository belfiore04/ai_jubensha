import { getAvatarColor, getInitial } from "../data";
import "./Avatar.css";

interface AvatarProps {
  id: string;
  name: string;
  avatar?: string;
  size?: number;
  active?: boolean;
  badge?: string;
  onClick?: () => void;
}

export default function Avatar({
  id,
  name,
  avatar,
  size = 48,
  active = false,
  badge,
  onClick,
}: AvatarProps) {
  const color = getAvatarColor(id);

  return (
    <div
      className={`avatar-wrapper ${active ? "avatar-active" : ""}`}
      onClick={onClick}
      style={{ width: size, height: size }}
    >
      <div
        className="avatar-circle"
        style={{
          width: size,
          height: size,
          background: avatar
            ? `url(${avatar}) center/cover`
            : `linear-gradient(135deg, ${color}, ${color}88)`,
          fontSize: size * 0.42,
          borderColor: active ? "var(--green)" : "transparent",
        }}
      >
        {!avatar && <span className="avatar-initial">{getInitial(name)}</span>}
      </div>
      {badge && <span className="avatar-badge">{badge}</span>}
    </div>
  );
}
