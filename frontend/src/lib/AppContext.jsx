import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { applyPalette } from "@/lib/theme/palettes";
import { applyPreset, applyTextScale } from "@/lib/theme/presets";
import { applyMotif } from "@/lib/theme/motifs";
import { profile as profileApi } from "@/lib/api";
import { toast } from "@/components/ui/use-toast";

// Profile preference keys we sync with the backend. Identity fields returned by
// GET /profile (id, email, phone, role, …) live on `user`, not `profile`.
const PROFILE_PREF_KEYS = [
  "name", "language", "state", "district", "occupation", "bio", "interests",
  "ai_model", "theme", "uiPreset", "motif", "textScale", "highContrast",
  "voiceEnabled", "festiveAccents", "ageBand", "gender", "languagesKnown", "onboarded",
];

function pickPrefs(obj) {
  const out = {};
  for (const k of PROFILE_PREF_KEYS) {
    if (obj[k] !== undefined && obj[k] !== null) out[k] = obj[k];
  }
  return out;
}

const AppContext = createContext(null);

const DEFAULT_PROFILE = {
  uiPreset: "sampann",
  theme: "saffron",
  motif: "minimal",
  textScale: "M",
  highContrast: false,
  voiceEnabled: false,
  festiveAccents: false,
  ageBand: null,
  gender: null,
  languagesKnown: ["hi", "en"],
  language: "en",
  state: null,
  district: null,
  occupation: null,
  interests: [],
  ai_model: "auto",
};

function loadFromStorage(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v ? JSON.parse(v) : fallback;
  } catch { return fallback; }
}

export function AppProvider({ children }) {
  const [token, setTokenState] = useState(() => localStorage.getItem("nipun_token"));
  const [user, setUserState] = useState(() => loadFromStorage("nipun_user", null));
  const [profile, setProfileState] = useState(() => loadFromStorage("nipun_profile", DEFAULT_PROFILE));
  const [activeSessionId, setActiveSessionId] = useState(null);
  // Whether the server profile has been fetched this session. Until it has, we can't tell if a
  // user already onboarded (their answers live on the server), so we must not force onboarding.
  const [profileHydrated, setProfileHydrated] = useState(!localStorage.getItem("nipun_token"));

  // Persist
  const setToken = useCallback((t) => {
    setTokenState(t);
    if (t) localStorage.setItem("nipun_token", t);
    else localStorage.removeItem("nipun_token");
  }, []);

  const setUser = useCallback((u) => {
    setUserState(u);
    if (u) localStorage.setItem("nipun_user", JSON.stringify(u));
    else localStorage.removeItem("nipun_user");
  }, []);

  const setProfile = useCallback((p) => {
    setProfileState(prev => {
      const next = typeof p === "function" ? p(prev) : { ...prev, ...p };
      localStorage.setItem("nipun_profile", JSON.stringify(next));
      return next;
    });
  }, []);

  // Update the profile locally AND persist it to the backend (best-effort).
  // Use this for any change that should survive across devices/logins.
  const updateProfileRemote = useCallback((partial) => {
    setProfile(partial);
    if (localStorage.getItem("nipun_token")) {
      return profileApi.update(partial).catch((err) => {
        // The local change already applied; surface that the server sync failed so the
        // user knows their preference may not persist across devices.
        console.error("Failed to save profile to server", err);
        toast({
          variant: "destructive",
          title: "Couldn't save your changes",
          description: "Your preference was applied on this device but didn't sync. Please try again.",
        });
      });
    }
    return Promise.resolve();
  }, [setProfile]);

  const clearAuth = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem("nipun_profile");
    setProfileState(DEFAULT_PROFILE);
  }, [setToken, setUser]);

  // Hydrate the profile from the backend once we have a token, so server-stored
  // preferences (appearance, onboarding answers) apply on a fresh device/login.
  useEffect(() => {
    if (!token) { setProfileHydrated(true); return; }
    let cancelled = false;
    setProfileHydrated(false);
    profileApi.get()
      .then((remote) => {
        if (cancelled || !remote) return;
        setProfile(pickPrefs(remote));
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setProfileHydrated(true); });
    return () => { cancelled = true; };
  }, [token, setProfile]);

  // Apply theme whenever profile changes
  useEffect(() => {
    if (profile) {
      applyPreset(profile.uiPreset || "sampann");
      applyPalette(profile.highContrast
        ? (profile.theme && profile.theme.startsWith("hc") ? profile.theme : "hc-light")
        : (profile.theme || "saffron"));
      applyMotif(profile.motif || "minimal");
      applyTextScale(profile.textScale || "M");
    }
  }, [profile]);

  // Onboarded if ANY of: this device remembers it, the SERVER profile's `onboarded` flag is set,
  // OR the profile ALREADY has real details filled. The server flag is the primary source of
  // truth (survives a fresh device / cleared storage). The "profile looks filled" inference sends
  // an EXISTING user whose details are already present straight to Home instead of re-showing
  // onboarding when the explicit flag is missing — e.g. accounts created before the `onboarded`
  // column existed, or seeded/admin users. These fields are only ever set during onboarding or in
  // Settings, so their presence means the user has effectively onboarded.
  const localOnboarded = user && loadFromStorage("nipun_onboarded_" + user?.id, false);
  const profileLooksFilled = !!(profile && (
    profile.state || profile.district || profile.occupation ||
    profile.ageBand || profile.gender || profile.bio ||
    (Array.isArray(profile.interests) && profile.interests.length > 0)
  ));
  const hasOnboarded = !!(user && (localOnboarded || profile?.onboarded || profileLooksFilled));

  const setOnboarded = useCallback(() => {
    if (user?.id) localStorage.setItem("nipun_onboarded_" + user.id, "true");
  }, [user]);

  // Self-heal: when we INFERRED onboarding from a filled profile but the server flag is still
  // unset, persist `onboarded=true` once so future logins are clean and don't depend on the
  // heuristic. Runs only after the server profile has hydrated, exactly once per correction.
  useEffect(() => {
    if (!profileHydrated || !user?.id) return;
    if (profile?.onboarded || localOnboarded || !profileLooksFilled) return;
    setOnboarded();
    if (localStorage.getItem("nipun_token")) {
      profileApi.update({ onboarded: true }).catch(() => {});
    }
  }, [profileHydrated, user, profile, localOnboarded, profileLooksFilled, setOnboarded]);

  return (
    <AppContext.Provider value={{
      token, setToken,
      user, setUser,
      profile, setProfile, updateProfileRemote,
      activeSessionId, setActiveSessionId,
      clearAuth,
      hasOnboarded, setOnboarded, profileHydrated,
      isAuthenticated: !!token,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}