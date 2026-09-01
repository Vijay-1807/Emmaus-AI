"use client";

import { create } from "zustand";

export interface User {
  id: string;
  email: string;
  name: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  created_at: string;
}

export interface AppState {
  user: User | null;
  workspace: Workspace | null;
  workspaces: Workspace[];
  setUser: (user: User | null) => void;
  setWorkspace: (ws: Workspace | null) => void;
  setWorkspaces: (wss: Workspace[]) => void;
}

export const useStore = create<AppState>((set) => ({
  user: null,
  workspace: null,
  workspaces: [],
  setUser: (user) => set({ user }),
  setWorkspace: (workspace) => set({ workspace }),
  setWorkspaces: (workspaces) => set({ workspaces }),
}));
