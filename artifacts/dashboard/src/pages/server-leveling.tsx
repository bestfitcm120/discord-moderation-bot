import {
  useGetMe,
  useGetLevelingConfig,
  useUpdateLevelingConfig,
  useGetLeaderboard,
  useListGuildChannels,
  useSearchGuildMembers,
  useGetMemberXp,
  useUpdateMemberXp,
  getGetMeQueryKey,
  getGetLevelingConfigQueryKey,
  getGetLeaderboardQueryKey,
  getListGuildChannelsQueryKey,
  getGetMemberXpQueryKey,
  getSearchGuildMembersQueryKey,
} from "@workspace/api-client-react";
import { useRoute, useLocation } from "wouter";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { ServerLayout } from "@/components/server-layout";
import { useToast } from "@/hooks/use-toast";
import { Toaster } from "@/components/ui/toaster";

function NumberInput({
  label,
  description,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  description?: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <div className="flex items-center justify-between gap-4 flex-wrap">
      <div>
        <div className="font-medium text-sm text-foreground">{label}</div>
        {description && <div className="text-xs text-muted-foreground mt-0.5">{description}</div>}
      </div>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground w-24 focus:outline-none focus:ring-2 focus:ring-primary/40"
      />
    </div>
  );
}

function ToggleSwitch({
  label,
  description,
  value,
  onChange,
}: {
  label: string;
  description?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 flex-wrap">
      <div>
        <div className="font-medium text-sm text-foreground">{label}</div>
        {description && <div className="text-xs text-muted-foreground mt-0.5">{description}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary/40 ${
          value ? "bg-primary" : "bg-secondary border border-border"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
            value ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

function ChannelSelect({
  value,
  onChange,
  channels,
  placeholder = "Select channel...",
}: {
  value: string | null;
  onChange: (v: string | null) => void;
  channels: Array<{ id: string; name: string }>;
  placeholder?: string;
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="text-sm bg-secondary border border-border rounded-lg px-3 py-1.5 text-foreground min-w-[200px] focus:outline-none focus:ring-2 focus:ring-primary/40"
    >
      <option value="">{placeholder}</option>
      {channels.map((c) => (
        <option key={c.id} value={c.id}>#{c.name}</option>
      ))}
    </select>
  );
}

function xpForLevel(level: number): number {
  return 100 * level * (level + 1) / 2;
}

function levelForXp(xp: number): number {
  // Inverse of xpForLevel: largest L where 50*L*(L+1) <= xp
  return Math.floor((-1 + Math.sqrt(1 + 4 * xp / 50)) / 2);
}

const RANK_MEDALS = ["🥇", "🥈", "🥉"];

function MemberCell({ entry }: { entry: { userId: string; username?: string | null; displayName?: string | null; avatarUrl?: string | null } }) {
  const name = entry.displayName ?? entry.username ?? entry.userId;
  const sub = entry.username && entry.username !== entry.displayName ? `@${entry.username}` : null;
  return (
    <div className="flex items-center gap-2.5">
      {entry.avatarUrl ? (
        <img src={entry.avatarUrl} alt="" className="w-8 h-8 rounded-full flex-shrink-0 object-cover" />
      ) : (
        <div className="w-8 h-8 rounded-full bg-secondary border border-border flex-shrink-0 flex items-center justify-center text-xs text-muted-foreground font-medium">
          {name.slice(0, 1).toUpperCase()}
        </div>
      )}
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground truncate">{name}</div>
        {sub && <div className="text-xs text-muted-foreground truncate">{sub}</div>}
      </div>
    </div>
  );
}

// ─── Manage XP tab ─────────────────────────────────────────────────────────

function ManageXpTab({ guildId }: { guildId: string }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string>("");
  const [selectedAvatar, setSelectedAvatar] = useState<string | null>(null);

  const [textXp, setTextXp] = useState(0);
  const [textLevel, setTextLevel] = useState(0);
  const [voiceXp, setVoiceXp] = useState(0);
  const [voiceLevel, setVoiceLevel] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  const { data: searchResults = [], isFetching: searching } = useSearchGuildMembers(
    guildId,
    { q: debouncedQuery },
    { query: { enabled: debouncedQuery.length >= 1, queryKey: getSearchGuildMembersQueryKey(guildId, { q: debouncedQuery }) } },
  );

  const { data: existingXp, isLoading: xpLoading } = useGetMemberXp(
    guildId,
    selectedUserId ?? "",
    { query: { enabled: !!selectedUserId, queryKey: getGetMemberXpQueryKey(guildId, selectedUserId ?? "") } },
  );

  useEffect(() => {
    if (existingXp) {
      setTextXp(existingXp.textXp);
      setTextLevel(existingXp.textLevel);
      setVoiceXp(existingXp.voiceXp);
      setVoiceLevel(existingXp.voiceLevel);
    }
  }, [existingXp]);

  const updateXp = useUpdateMemberXp();

  function selectMember(userId: string, displayName: string, avatarUrl: string | null | undefined) {
    setSelectedUserId(userId);
    setSelectedName(displayName);
    setSelectedAvatar(avatarUrl ?? null);
    setQuery("");
    setDebouncedQuery("");
  }

  async function handleSave() {
    if (!selectedUserId) return;
    try {
      await updateXp.mutateAsync({
        guildId,
        userId: selectedUserId,
        data: { textXp, textLevel, voiceXp, voiceLevel },
      });
      queryClient.invalidateQueries({ queryKey: getGetMemberXpQueryKey(guildId, selectedUserId) });
      queryClient.invalidateQueries({ queryKey: getGetLeaderboardQueryKey(guildId, { category: "text" }) });
      queryClient.invalidateQueries({ queryKey: getGetLeaderboardQueryKey(guildId, { category: "voice" }) });
      toast({ title: "XP updated", description: `${selectedName}'s XP has been saved.` });
    } catch {
      toast({ title: "Save failed", description: "Could not update XP.", variant: "destructive" });
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-300/80 space-y-1">
        <p className="font-semibold text-amber-300">Admin XP Override</p>
        <p>Search for a member, then directly set their text or voice XP and level. The leaderboard updates immediately.</p>
      </div>

      {/* Search */}
      <div className="relative">
        <input
          type="text"
          placeholder="Search member by name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
        />
        {debouncedQuery && searchResults.length > 0 && !selectedUserId && (
          <div className="absolute z-10 top-full mt-1 w-full rounded-xl border border-border bg-card shadow-xl overflow-hidden">
            {searchResults.map((m) => {
              const name = m.displayName ?? m.username ?? m.userId;
              return (
                <button
                  key={m.userId}
                  type="button"
                  onClick={() => selectMember(m.userId!, name, m.avatarUrl)}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 hover:bg-secondary/60 transition-colors text-left"
                >
                  {m.avatarUrl ? (
                    <img src={m.avatarUrl} alt="" className="w-7 h-7 rounded-full flex-shrink-0 object-cover" />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-secondary border border-border flex-shrink-0 flex items-center justify-center text-xs text-muted-foreground">
                      {name.slice(0, 1).toUpperCase()}
                    </div>
                  )}
                  <div>
                    <div className="text-sm text-foreground font-medium">{name}</div>
                    {m.username && m.username !== name && (
                      <div className="text-xs text-muted-foreground">@{m.username}</div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
        {searching && debouncedQuery && (
          <div className="absolute right-3 top-2.5 text-muted-foreground text-xs">searching…</div>
        )}
      </div>

      {/* Selected member + editor */}
      {selectedUserId && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          {/* Member header */}
          <div className="px-5 py-3 border-b border-border bg-secondary/30 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              {selectedAvatar ? (
                <img src={selectedAvatar} alt="" className="w-8 h-8 rounded-full object-cover flex-shrink-0" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-secondary border border-border flex-shrink-0 flex items-center justify-center text-xs text-muted-foreground">
                  {selectedName.slice(0, 1).toUpperCase()}
                </div>
              )}
              <span className="text-sm font-semibold text-foreground">{selectedName}</span>
            </div>
            <button
              type="button"
              onClick={() => { setSelectedUserId(null); setSelectedName(""); setSelectedAvatar(null); }}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              change member
            </button>
          </div>

          <div className="p-5 space-y-5">
            {xpLoading ? (
              <div className="space-y-3">{[1, 2].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
            ) : (
              <>
                {/* Text XP */}
                <div>
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">💬 Text</div>
                  <div className="space-y-3">
                    <NumberInput label="Text XP" value={textXp} min={0} onChange={(xp) => { setTextXp(xp); setTextLevel(levelForXp(xp)); }} />
                    <NumberInput label="Text Level" value={textLevel} min={0} onChange={(lvl) => { setTextLevel(lvl); setTextXp(xpForLevel(lvl)); }} />
                  </div>
                </div>

                <div className="border-t border-border" />

                {/* Voice XP */}
                <div>
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">🔊 Voice</div>
                  <div className="space-y-3">
                    <NumberInput label="Voice XP" value={voiceXp} min={0} onChange={(xp) => { setVoiceXp(xp); setVoiceLevel(levelForXp(xp)); }} />
                    <NumberInput label="Voice Level" value={voiceLevel} min={0} onChange={(lvl) => { setVoiceLevel(lvl); setVoiceXp(xpForLevel(lvl)); }} />
                  </div>
                </div>

                <button
                  onClick={handleSave}
                  disabled={updateXp.isPending}
                  className="w-full px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {updateXp.isPending ? "Saving…" : "Save XP Changes"}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {!selectedUserId && (
        <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          Search for a member above to edit their XP.
        </div>
      )}
    </div>
  );
}

// ─── Page ──────────────────────────────────────────────────────────────────

export default function ServerLeveling() {
  const [, params] = useRoute("/servers/:guildId/leveling");
  const guildId = params?.guildId ?? "";
  const [, setLocation] = useLocation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"settings" | "text" | "voice" | "manage">("settings");
  const [dirty, setDirty] = useState(false);

  const { data: user, isLoading: userLoading } = useGetMe({
    query: { queryKey: getGetMeQueryKey(), retry: false },
  });

  const { data: config, isLoading: configLoading } = useGetLevelingConfig(guildId, {
    query: { enabled: !!guildId && !!user, queryKey: getGetLevelingConfigQueryKey(guildId) },
  });

  const { data: textLb = [], isLoading: textLbLoading } = useGetLeaderboard(guildId, { category: "text" }, {
    query: {
      enabled: !!guildId && !!user && activeTab === "text",
      queryKey: getGetLeaderboardQueryKey(guildId, { category: "text" }),
    },
  });

  const { data: voiceLb = [], isLoading: voiceLbLoading } = useGetLeaderboard(guildId, { category: "voice" }, {
    query: {
      enabled: !!guildId && !!user && activeTab === "voice",
      queryKey: getGetLeaderboardQueryKey(guildId, { category: "voice" }),
    },
  });

  const { data: textChannels = [] } = useListGuildChannels(guildId, {}, {
    query: { enabled: !!guildId && !!user, queryKey: getListGuildChannelsQueryKey(guildId, {}) },
  });

  const updateConfig = useUpdateLevelingConfig();

  const [textXpMin, setTextXpMin] = useState(15);
  const [textXpMax, setTextXpMax] = useState(25);
  const [textXpCooldown, setTextXpCooldown] = useState(60);
  const [voiceXpPerMinute, setVoiceXpPerMinute] = useState(10);
  const [levelupChannelId, setLevelupChannelId] = useState<string | null>(null);
  const [levelupMessageEnabled, setLevelupMessageEnabled] = useState(true);

  useEffect(() => {
    if (!userLoading && !user) setLocation("/");
  }, [user, userLoading, setLocation]);

  useEffect(() => {
    if (config) {
      setTextXpMin(config.textXpMin);
      setTextXpMax(config.textXpMax);
      setTextXpCooldown(config.textXpCooldown);
      setVoiceXpPerMinute(config.voiceXpPerMinute);
      setLevelupChannelId(config.levelupChannelId ?? null);
      setLevelupMessageEnabled(config.levelupMessageEnabled);
      setDirty(false);
    }
  }, [config]);

  function markDirty() { setDirty(true); }

  async function handleSave() {
    try {
      await updateConfig.mutateAsync({
        guildId,
        data: {
          textXpMin,
          textXpMax,
          textXpCooldown,
          voiceXpPerMinute,
          levelupChannelId,
          levelupMessageEnabled,
        },
      });
      queryClient.invalidateQueries({ queryKey: getGetLevelingConfigQueryKey(guildId) });
      setDirty(false);
      toast({ title: "Settings saved", description: "Leveling configuration updated." });
    } catch {
      toast({ title: "Save failed", description: "Could not save configuration.", variant: "destructive" });
    }
  }

  if (!user) return null;

  const filteredText = textChannels.filter((c) => c.type === 0 || c.type === 5);

  return (
    <ServerLayout guildId={guildId} activePage="leveling">
      <div className="space-y-6 pb-10">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-foreground">Leveling System</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Configure XP gains, level-up announcements, and manage member XP.
            </p>
          </div>
          {activeTab === "settings" && (
            <button
              onClick={handleSave}
              disabled={!dirty || updateConfig.isPending}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {updateConfig.isPending ? "Saving..." : "Save Changes"}
            </button>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-border overflow-x-auto">
          {[
            { key: "settings", label: "⚙️ Settings" },
            { key: "text", label: "💬 Text Leaderboard" },
            { key: "voice", label: "🔊 Voice Leaderboard" },
            { key: "manage", label: "✏️ Manage XP" },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as typeof activeTab)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px whitespace-nowrap ${
                activeTab === tab.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Settings Tab */}
        {activeTab === "settings" && (
          <>
            {configLoading ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
              </div>
            ) : (
              <div className="space-y-4">
                {/* How it works info */}
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-300/80 space-y-1">
                  <p className="font-semibold text-amber-300">How XP works</p>
                  <ul className="list-disc list-inside space-y-0.5">
                    <li>Members earn text XP per message (with cooldown to prevent spam)</li>
                    <li>Members earn voice XP per minute spent in a voice channel</li>
                    <li>Levels are calculated from total accumulated XP</li>
                    <li>Use <code className="bg-amber-500/10 px-1 rounded">/rank</code> and <code className="bg-amber-500/10 px-1 rounded">/top</code> in Discord to view progress</li>
                  </ul>
                </div>

                {/* Text XP */}
                <div className="rounded-xl border border-border bg-card overflow-hidden">
                  <div className="px-5 py-3 border-b border-border bg-secondary/30">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      💬 Text XP Settings
                    </span>
                  </div>
                  <div className="p-5 space-y-4 divide-y divide-border">
                    <div className="pb-4">
                      <NumberInput
                        label="Min XP per Message"
                        description="Minimum XP awarded per message."
                        value={textXpMin}
                        min={1}
                        max={100}
                        onChange={(v) => { setTextXpMin(v); markDirty(); }}
                      />
                    </div>
                    <div className="py-4">
                      <NumberInput
                        label="Max XP per Message"
                        description="Maximum XP awarded per message (randomly between min and max)."
                        value={textXpMax}
                        min={1}
                        max={200}
                        onChange={(v) => { setTextXpMax(v); markDirty(); }}
                      />
                    </div>
                    <div className="pt-4">
                      <NumberInput
                        label="Cooldown (seconds)"
                        description="Seconds between XP awards per user. Prevents spam farming."
                        value={textXpCooldown}
                        min={5}
                        max={3600}
                        onChange={(v) => { setTextXpCooldown(v); markDirty(); }}
                      />
                    </div>
                  </div>
                </div>

                {/* Voice XP */}
                <div className="rounded-xl border border-border bg-card overflow-hidden">
                  <div className="px-5 py-3 border-b border-border bg-secondary/30">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      🔊 Voice XP Settings
                    </span>
                  </div>
                  <div className="p-5">
                    <NumberInput
                      label="XP per Minute in Voice"
                      description="XP awarded for each minute spent in any voice channel."
                      value={voiceXpPerMinute}
                      min={1}
                      max={100}
                      onChange={(v) => { setVoiceXpPerMinute(v); markDirty(); }}
                    />
                  </div>
                </div>

                {/* Level-up announcements */}
                <div className="rounded-xl border border-border bg-card overflow-hidden">
                  <div className="px-5 py-3 border-b border-border bg-secondary/30">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      🎉 Level-Up Announcements
                    </span>
                  </div>
                  <div className="p-5 space-y-4 divide-y divide-border">
                    <div className="pb-4">
                      <ToggleSwitch
                        label="Enable Level-Up Messages"
                        description="Send a celebration message when a member levels up."
                        value={levelupMessageEnabled}
                        onChange={(v) => { setLevelupMessageEnabled(v); markDirty(); }}
                      />
                    </div>
                    <div className="pt-4">
                      <div className="flex items-center justify-between gap-4 flex-wrap">
                        <div>
                          <div className="font-medium text-sm text-foreground">Level-Up Channel</div>
                          <div className="text-xs text-muted-foreground mt-0.5">
                            Channel where level-up celebrations are announced.
                          </div>
                        </div>
                        <ChannelSelect
                          value={levelupChannelId}
                          onChange={(v) => { setLevelupChannelId(v); markDirty(); }}
                          channels={filteredText}
                          placeholder="Disabled — pick a channel"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Level scale reference */}
                <div className="rounded-xl border border-border bg-card overflow-hidden">
                  <div className="px-5 py-3 border-b border-border bg-secondary/30">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Level Scale Reference
                    </span>
                  </div>
                  <div className="p-5">
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                      {[1, 2, 3, 5, 10, 15, 20, 30, 50].map((lvl) => (
                        <div key={lvl} className="rounded-lg bg-secondary/40 px-3 py-2 flex justify-between">
                          <span className="text-muted-foreground">Level {lvl}</span>
                          <span className="text-foreground font-medium">{xpForLevel(lvl).toLocaleString()} XP</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {/* Text Leaderboard Tab */}
        {activeTab === "text" && (
          <div className="rounded-xl border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Rank</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Member</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Level</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">XP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {textLbLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 4 }).map((_, j) => (
                        <td key={j} className="px-4 py-3"><Skeleton className="h-4 w-20" /></td>
                      ))}
                    </tr>
                  ))
                ) : textLb.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-muted-foreground text-sm">
                      No text XP data yet. Members earn XP by sending messages.
                    </td>
                  </tr>
                ) : (
                  textLb.map((entry) => (
                    <tr key={entry.userId} className="hover:bg-secondary/20 transition-colors">
                      <td className="px-4 py-3 font-bold text-foreground">
                        {RANK_MEDALS[entry.rank - 1] ?? `#${entry.rank}`}
                      </td>
                      <td className="px-4 py-3">
                        <MemberCell entry={entry} />
                      </td>
                      <td className="px-4 py-3 text-primary font-semibold">{entry.level}</td>
                      <td className="px-4 py-3 text-muted-foreground">{entry.xp.toLocaleString()}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Voice Leaderboard Tab */}
        {activeTab === "voice" && (
          <div className="rounded-xl border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Rank</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Member</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Level</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">XP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {voiceLbLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 4 }).map((_, j) => (
                        <td key={j} className="px-4 py-3"><Skeleton className="h-4 w-20" /></td>
                      ))}
                    </tr>
                  ))
                ) : voiceLb.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-muted-foreground text-sm">
                      No voice XP data yet. Members earn XP by spending time in voice channels.
                    </td>
                  </tr>
                ) : (
                  voiceLb.map((entry) => (
                    <tr key={entry.userId} className="hover:bg-secondary/20 transition-colors">
                      <td className="px-4 py-3 font-bold text-foreground">
                        {RANK_MEDALS[entry.rank - 1] ?? `#${entry.rank}`}
                      </td>
                      <td className="px-4 py-3">
                        <MemberCell entry={entry} />
                      </td>
                      <td className="px-4 py-3 text-primary font-semibold">{entry.level}</td>
                      <td className="px-4 py-3 text-muted-foreground">{entry.xp.toLocaleString()}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Manage XP Tab */}
        {activeTab === "manage" && <ManageXpTab guildId={guildId} />}
      </div>
      <Toaster />
    </ServerLayout>
  );
}
