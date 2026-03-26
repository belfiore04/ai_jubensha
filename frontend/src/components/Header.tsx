import { useNavigate } from "react-router-dom";
import "./Header.css";

interface HeaderProps {
  title: string;
  showBack?: boolean;
  onClueClick?: () => void;
  onHintClick?: () => void;
  bgmPlaying?: boolean;
  onBgmToggle?: () => void;
}

export default function Header({
  title,
  showBack = false,
  onClueClick,
  onHintClick,
  bgmPlaying,
  onBgmToggle,
}: HeaderProps) {
  const navigate = useNavigate();

  return (
    <header className="header">
      <div className="header-left">
        {showBack && (
          <button className="header-btn" onClick={() => navigate(-1)}>
            <span className="header-back-icon">&larr;</span>
          </button>
        )}
      </div>

      <h1 className="header-title">{title}</h1>

      <div className="header-right">
        {onBgmToggle && (
          <button
            className={`header-btn ${bgmPlaying ? "header-btn--active" : ""}`}
            onClick={onBgmToggle}
            title={bgmPlaying ? "暂停音乐" : "播放音乐"}
          >
            {bgmPlaying ? "♫" : "♪"}
          </button>
        )}
        {onClueClick && (
          <button className="header-btn" onClick={onClueClick}>
            线索
          </button>
        )}
        {onHintClick && (
          <button className="header-btn" onClick={onHintClick}>
            提示
          </button>
        )}
      </div>
    </header>
  );
}
