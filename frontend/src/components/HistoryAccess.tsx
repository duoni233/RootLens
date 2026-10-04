import { KeyRound, LockKeyhole } from "lucide-react";
import { useState } from "react";
import { useHistoryAccess } from "../historyAccess";
import { api, apiErrorMessage } from "../lib/api";

export function HistoryAccess({ error }: { error?: string }) {
  const { unlock } = useHistoryAccess();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [validationError, setValidationError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate || busy) return;
    setBusy(true);
    setValidationError("");
    try {
      await api.history({ limit: 1, offset: 0 }, candidate);
      unlock(candidate);
      setValue("");
    } catch (cause) {
      setValidationError(apiErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="access-panel" aria-label="解锁诊断历史">
      <LockKeyhole size={26} />
      <h2>诊断历史已锁定</h2>
      <p>输入私有演示访问令牌。令牌只保存在当前浏览器会话中。</p>
      {(validationError || error) && (
        <p className="form-error" role="alert">
          {validationError || error}
        </p>
      )}
      <form onSubmit={submit}>
        <label htmlFor="history-token">访问令牌</label>
        <div className="access-input-row">
          <input
            id="history-token"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setValidationError("");
            }}
            required
          />
          <button className="button-primary" type="submit" disabled={busy}>
            <KeyRound size={16} /> {busy ? "验证中…" : "解锁"}
          </button>
        </div>
      </form>
      <small>这不是生产环境用户认证。请仅在可信的私有网络使用。</small>
    </section>
  );
}
