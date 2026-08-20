import React, { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Search, Loader2, Pencil, Trash2, RefreshCw, Eye, Upload } from "lucide-react";
import { admin as adminApi } from "@/lib/api";

export default function AdminUsers() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterRole, setFilterRole] = useState("");
  const [filterActive, setFilterActive] = useState("");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({});

  useEffect(() => { loadUsers(); }, [filterRole, filterActive]);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (filterRole) params.role = filterRole;
      if (filterActive) params.is_active = filterActive === "true";
      const data = await adminApi.getUsers(params);
      setUsers(Array.isArray(data) ? data : []);
    } catch {}
    setLoading(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Deactivate this user?")) return;
    try { await adminApi.deleteUser(id); loadUsers(); } catch {}
  };

  const handleResetPw = async (id) => {
    if (!window.confirm("Force password reset for this user?")) return;
    try { await adminApi.resetUserPassword(id); alert("Password reset initiated."); } catch {}
  };

  const handleSaveEdit = async () => {
    if (!editing) return;
    try { await adminApi.updateUser(editing, editForm); setEditing(null); loadUsers(); } catch {}
  };

  const filtered = users.filter(u => !search || (u.name || u.email || "").toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="min-h-screen" style={{ background: "var(--background)" }}>
      <div className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-3">
          <button onClick={() => navigate("/admin")} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }}><ArrowLeft size={18} /></button>
          <h1 className="text-lg font-heading font-semibold" style={{ color: "var(--text)" }}>User Management</h1>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-6">
        <div className="flex flex-wrap gap-3 mb-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border flex-1 max-w-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
            <Search size={14} style={{ color: "var(--text-muted)" }} />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search users…"
              className="flex-1 text-sm bg-transparent outline-none" style={{ color: "var(--text)" }} />
          </div>
          <select value={filterRole} onChange={e => setFilterRole(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-sm border" style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}>
            <option value="">All roles</option>
            <option value="admin">Admin</option>
            <option value="user">User</option>
          </select>
          <select value={filterActive} onChange={e => setFilterActive(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-sm border" style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}>
            <option value="">All status</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </div>

        {loading ? (
          <div className="flex justify-center py-12"><Loader2 size={24} className="animate-spin" style={{ color: "var(--text-muted)" }} /></div>
        ) : (
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)" }}>
            <table className="w-full text-sm">
              <thead>
                <tr style={{ background: "var(--surface-sunken)" }}>
                  <th className="px-4 py-2.5 text-left font-medium text-xs" style={{ color: "var(--text-secondary)" }}>Name</th>
                  <th className="px-4 py-2.5 text-left font-medium text-xs hidden sm:table-cell" style={{ color: "var(--text-secondary)" }}>Email</th>
                  <th className="px-4 py-2.5 text-left font-medium text-xs" style={{ color: "var(--text-secondary)" }}>Role</th>
                  <th className="px-4 py-2.5 text-left font-medium text-xs" style={{ color: "var(--text-secondary)" }}>Status</th>
                  <th className="px-4 py-2.5 text-right font-medium text-xs" style={{ color: "var(--text-secondary)" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(u => (
                  <tr key={u.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                    <td className="px-4 py-2.5" style={{ color: "var(--text)" }}>
                      {editing === u.id ? (
                        <input value={editForm.name || ""} onChange={e => setEditForm(prev => ({ ...prev, name: e.target.value }))}
                          className="text-sm border-b bg-transparent outline-none" style={{ borderColor: "var(--accent)", color: "var(--text)" }} />
                      ) : u.name}
                    </td>
                    <td className="px-4 py-2.5 hidden sm:table-cell" style={{ color: "var(--text-muted)" }}>{u.email}</td>
                    <td className="px-4 py-2.5">
                      <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: u.role === "admin" ? "var(--accent-subtle)" : "var(--surface-sunken)", color: u.role === "admin" ? "var(--accent)" : "var(--text-muted)" }}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="w-2 h-2 rounded-full inline-block" style={{ background: u.is_active !== false ? "var(--success)" : "var(--text-muted)" }} />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex justify-end gap-1">
                        {editing === u.id ? (
                          <>
                            <button onClick={handleSaveEdit} className="p-1 rounded text-xs" style={{ color: "var(--accent)" }}>Save</button>
                            <button onClick={() => setEditing(null)} className="p-1 rounded text-xs" style={{ color: "var(--text-muted)" }}>Cancel</button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => { setEditing(u.id); setEditForm({ name: u.name, role: u.role }); }} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }} title="Edit"><Pencil size={12} /></button>
                            <button onClick={() => handleResetPw(u.id)} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }} title="Reset password"><RefreshCw size={12} /></button>
                            <button onClick={() => handleDelete(u.id)} className="p-1 rounded hover:opacity-80" style={{ color: "var(--destructive)" }} title="Deactivate"><Trash2 size={12} /></button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}