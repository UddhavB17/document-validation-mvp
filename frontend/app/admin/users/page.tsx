"use client";

import { FormEvent, useState } from "react";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import type { AdminUser } from "@/lib/api";
import {
  useAdminUsers,
  useCreateAdminUser,
  useDeleteAdminUser,
  useResetAdminPassword,
  useUpdateAdminUser,
} from "@/lib/queries";

export default function AdminUsersPage() {
  const users = useAdminUsers();
  const createUser = useCreateAdminUser();
  const updateUser = useUpdateAdminUser();
  const resetPassword = useResetAdminPassword();
  const deleteUser = useDeleteAdminUser();
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setNotice(null);
    const form = new FormData(event.currentTarget);
    const payload = {
      email: String(form.get("email") ?? "").trim(),
      display_name: String(form.get("display_name") ?? "").trim(),
      role: String(form.get("role") ?? "user"),
      password: String(form.get("password") ?? ""),
    };
    if (!payload.email || !payload.display_name || !payload.password) {
      setFormError("Email, display name, and password are required.");
      return;
    }
    try {
      await createUser.mutateAsync(payload);
      (event.target as HTMLFormElement).reset();
      setNotice(`Created ${payload.email}.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not create the user.");
    }
  }

  async function handleToggleActive(user: AdminUser) {
    setFormError(null);
    setNotice(null);
    try {
      await updateUser.mutateAsync({ userId: user.id, patch: { is_active: !user.is_active } });
      setNotice(`${user.email} is now ${user.is_active ? "inactive" : "active"}.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not update the user.");
    }
  }

  async function handleResetPassword(user: AdminUser) {
    setFormError(null);
    setNotice(null);
    const next = window.prompt(`Set a new password for ${user.email}:`);
    if (!next) {
      return;
    }
    try {
      await resetPassword.mutateAsync({ userId: user.id, newPassword: next });
      setNotice(`Password updated for ${user.email}.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not reset the password.");
    }
  }

  async function handleRemove(user: AdminUser) {
    setFormError(null);
    setNotice(null);
    const confirmed = window.confirm(
      `Permanently remove ${user.email}? They will lose access immediately. This cannot be undone.`,
    );
    if (!confirmed) {
      return;
    }
    try {
      await deleteUser.mutateAsync(user.id);
      setNotice(`Removed ${user.email}.`);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not remove the user.");
    }
  }

  const rows = users.data?.users ?? [];

  return (
    <div className="mx-auto max-w-[1100px] space-y-6">
      <PageHeader title="Users" description="Create user and admin accounts, deactivate access, and reset passwords." />

      {users.isLoading ? <LoadingMessage message="Loading users…" /> : null}
      {users.isError ? <ErrorMessage message="Could not load users. Refresh to try again." /> : null}
      {formError ? <ErrorMessage message={formError} /> : null}
      {notice ? <InfoMessage message={notice} /> : null}

      <section aria-labelledby="admin-users-create" className="rounded-xl border border-[#E1E5EB] bg-white p-5 shadow-sm">
        <h2 id="admin-users-create" className="text-base font-bold text-slate-900">Create a user</h2>
        <form onSubmit={handleCreate} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-semibold text-slate-700">
            Email
            <input name="email" type="email" required autoComplete="off" className="rounded-lg border border-[#E1E5EB] px-3 py-2 font-normal text-slate-900 focus:border-[#2B4C7E] focus:outline-none" />
          </label>
          <label className="flex flex-col gap-1 text-sm font-semibold text-slate-700">
            Display name
            <input name="display_name" type="text" required autoComplete="off" className="rounded-lg border border-[#E1E5EB] px-3 py-2 font-normal text-slate-900 focus:border-[#2B4C7E] focus:outline-none" />
          </label>
          <label className="flex flex-col gap-1 text-sm font-semibold text-slate-700">
            Role
            <select name="role" defaultValue="user" className="rounded-lg border border-[#E1E5EB] px-3 py-2 font-normal text-slate-900 focus:border-[#2B4C7E] focus:outline-none">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-semibold text-slate-700">
            Temporary password
            <input name="password" type="password" required autoComplete="new-password" className="rounded-lg border border-[#E1E5EB] px-3 py-2 font-normal text-slate-900 focus:border-[#2B4C7E] focus:outline-none" />
          </label>
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={createUser.isPending}
              className="rounded-lg bg-[#2B4C7E] px-5 py-2.5 text-sm font-bold text-white hover:bg-[#1E3559] disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {createUser.isPending ? "Creating…" : "Create user"}
            </button>
          </div>
        </form>
      </section>

      {users.data ? (
        <section aria-labelledby="admin-users-list" className="overflow-x-auto rounded-xl border border-[#E1E5EB] bg-white">
          <h2 id="admin-users-list" className="sr-only">Existing users</h2>
          <table className="min-w-full border-collapse text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-3 py-2.5">Email</th>
                <th scope="col" className="px-3 py-2.5">Name</th>
                <th scope="col" className="px-3 py-2.5">Role</th>
                <th scope="col" className="px-3 py-2.5">Active</th>
                <th scope="col" className="px-3 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 text-slate-800">
              {rows.map((user) => (
                <tr key={user.id}>
                  <td className="px-3 py-3 font-mono text-xs font-bold">{user.email}</td>
                  <td className="px-3 py-3 font-semibold">{user.display_name}</td>
                  <td className="px-3 py-3">{user.role}</td>
                  <td className="px-3 py-3">{user.is_active ? "Yes" : "No"}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void handleToggleActive(user)}
                        disabled={updateUser.isPending}
                        className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        {user.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleResetPassword(user)}
                        disabled={resetPassword.isPending}
                        className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      >
                        Reset password
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleRemove(user)}
                        disabled={deleteUser.isPending}
                        className="rounded-md border border-red-300 bg-white px-2.5 py-1.5 text-xs font-bold text-red-700 hover:bg-red-50 disabled:opacity-50"
                      >
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}
