import type { Character, CharacterRoleMapping, Role } from "../types";
import Avatar from "./Avatar";
import "./AvatarRow.css";

interface AvatarRowProps {
  characters: Character[];
  mappings?: CharacterRoleMapping[];
  roles?: Role[];
  playerCharacterId?: string | null;
  currentSpeakerId?: string;
}

export default function AvatarRow({
  characters,
  mappings = [],
  roles = [],
  playerCharacterId,
  currentSpeakerId,
}: AvatarRowProps) {
  function getBadge(charId: string): string | undefined {
    if (charId === playerCharacterId) return "你";
    const mapping = mappings.find((m) => m.character_id === charId);
    if (mapping && !mapping.is_player) return "AI";
    return undefined;
  }

  function getRoleName(charId: string): string | undefined {
    const mapping = mappings.find((m) => m.character_id === charId);
    if (!mapping) return undefined;
    const role = roles.find((r) => r.id === mapping.role_id);
    return role?.name;
  }

  return (
    <div className="avatar-row">
      <div className="avatar-row-scroll">
        {characters.map((c) => {
          const roleName = getRoleName(c.id);
          return (
            <div key={c.id} className="avatar-row-item">
              <Avatar
                id={c.id}
                name={c.name}
                avatar={c.avatar || undefined}
                size={44}
                active={c.id === currentSpeakerId}
                badge={getBadge(c.id)}
              />
              <span className="avatar-row-name">{c.name}</span>
              {roleName && (
                <span className="avatar-row-role">{roleName}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
