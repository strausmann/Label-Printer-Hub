import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { invalidImport, prefixTaken } from "../../api/errorDetail";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { ModalDialog, TextInput } from "../settings/controls";
import { SECONDARY_BUTTON } from "../ui";
import { useImportType, type ExportDoc, type ImportOptions, type ImportResponse } from "./api";
import { useArchiveErrorText } from "./errors";
import { TextAreaField } from "./fields";
import { KEY, PREFIX } from "./patterns";

/** The server refuses larger documents (413); the dialog checks first so nothing is uploaded for nothing. */
export const MAX_IMPORT_BYTES = 64 * 1024;

type Problem = { text: string; list?: string[] } | null;
type Phase = "input" | "conflict" | "done";

/** Import a sheet type export: paste it or choose the file, then decide what to do when the key exists. */
export function ImportDialog({ isOpen, onClose, onShow }: { isOpen: boolean; onClose: () => void; onShow: (key: string) => void }) {
  const { t } = useLingui();
  const errorText = useArchiveErrorText();
  const importType = useImportType();
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>("input");
  const [problem, setProblem] = useState<Problem>(null);
  const [existingKey, setExistingKey] = useState("");
  const [newKeyChoice, setNewKeyChoice] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newPrefix, setNewPrefix] = useState("");
  const [prefixRequired, setPrefixRequired] = useState(false);
  const [result, setResult] = useState<ImportResponse | null>(null);

  function close() {
    setText("");
    setPhase("input");
    setProblem(null);
    setNewKeyChoice(false);
    setNewKey("");
    setNewPrefix("");
    setPrefixRequired(false);
    setResult(null);
    importType.reset();
    onClose();
  }

  /** The document the text holds, or the sentence that says why it cannot be sent. */
  function readDoc(): ExportDoc | string {
    if (text.trim() === "") return t`Paste the export file or choose it.`;
    if (new TextEncoder().encode(text).length > MAX_IMPORT_BYTES) return t`The text is larger than 64 KB.`;
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch {
      return t`That text is not valid JSON.`;
    }
    if (typeof value !== "object" || value === null || Array.isArray(value)) return t`This is not a sheet type export file.`;
    return value as ExportDoc;
  }

  async function chooseFile(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_IMPORT_BYTES) return setProblem({ text: t`The file is larger than 64 KB.` });
    setProblem(null);
    setText(await file.text());
  }

  /** The new key and prefix the person typed, checked against the server's shapes before anything is sent. */
  function checkNames(options: ImportOptions): string | null {
    if (options.new_key !== undefined && !KEY.test(options.new_key)) {
      return t`The key uses lowercase letters, digits and dashes, 3 to 64 characters, and starts and ends with a letter or digit.`;
    }
    const prefixMissing = prefixRequired && options.mode !== "new_version" && options.new_prefix === undefined;
    if (prefixMissing || (options.new_prefix !== undefined && !PREFIX.test(options.new_prefix))) {
      return t`The code prefix is 2 to 10 capital letters or digits and starts with a letter.`;
    }
    return null;
  }

  async function send(options: ImportOptions) {
    const doc = readDoc();
    if (typeof doc === "string") return setProblem({ text: doc });
    const names = checkNames(options);
    if (names) return setProblem({ text: names });
    setProblem(null);
    try {
      setResult(await importType.mutateAsync({ doc, options }));
      setPhase("done");
    } catch (error) {
      if (error instanceof ApiError && error.code === "type_exists" && !options.mode) {
        setExistingKey(typeof doc.type?.key === "string" ? doc.type.key : "");
        setPhase("conflict");
        return;
      }
      const invalid = invalidImport(error);
      if (invalid) return setProblem({ text: t`This is not a valid sheet type export.`, list: invalid.errors });
      if (prefixTaken(error)) {
        setPrefixRequired(true);
        return setProblem({ text: t`Another type already uses this code prefix. Choose another one.` });
      }
      if (error instanceof ApiError && error.code === "import_too_large") {
        return setProblem({ text: t`The server refused the file: it is larger than 64 KB.` });
      }
      setProblem({ text: errorText(error, t`The import failed.`) });
    }
  }

  const prefixOption = (): Pick<ImportOptions, "new_prefix"> => (newPrefix.trim() === "" ? {} : { new_prefix: newPrefix.trim() });
  const alert = problem ? (
    <div role="alert" className="text-ink">
      <p>{problem.text}</p>
      {problem.list ? (
        <ul className="mt-1 list-disc pl-5 font-mono text-small [overflow-wrap:anywhere]">
          {problem.list.map((entry) => (
            <li key={entry}>{entry}</li>
          ))}
        </ul>
      ) : null}
    </div>
  ) : null;

  const outcomes: Record<ImportResponse["outcome"], string> = result
    ? {
        created: t`Created the type ${result.key}.`,
        unchanged: t`Nothing changed: ${result.key} already has this geometry.`,
        version_added: t`Added version ${result.version} to ${result.key}.`,
        created_as_new_key: t`Created the type ${result.key} as a new key.`,
      }
    : { created: "", unchanged: "", version_added: "", created_as_new_key: "" };

  return (
    <ModalDialog title={t`Import a sheet type`} isOpen={isOpen} onClose={close}>
      <div className="flex max-h-[70dvh] flex-col gap-4 overflow-y-auto">
        {phase === "done" && result ? (
          <>
            <p role="status">{outcomes[result.outcome]}</p>
            <div className="flex flex-wrap gap-3">
              <Button
                className={PRIMARY_BUTTON}
                onPress={() => {
                  onShow(result.key);
                  close();
                }}
              >
                {t`Show the type`}
              </Button>
              <Button onPress={close} className={SECONDARY_BUTTON}>{t`Close`}</Button>
            </div>
          </>
        ) : phase === "conflict" ? (
          <>
            <p>{t`A sheet type with the key ${existingKey} already exists. Add this geometry to it as a new version, or keep both and import this one under a new key.`}</p>
            <div className="flex flex-wrap gap-3">
              <Button isDisabled={importType.isPending} onPress={() => void send({ mode: "new_version" })} className={PRIMARY_BUTTON}>
                {t`Add as new version`}
              </Button>
              <Button aria-expanded={newKeyChoice} onPress={() => setNewKeyChoice(true)} className={SECONDARY_BUTTON}>
                {t`Import under a new key`}
              </Button>
            </div>
            {newKeyChoice ? (
              <div className="flex flex-col gap-4">
                <TextInput label={t`New key`} value={newKey} onChange={setNewKey} mono />
                <TextInput
                  label={prefixRequired ? t`New code prefix` : t`New code prefix (optional)`}
                  value={newPrefix}
                  onChange={(v) => setNewPrefix(v.toUpperCase())}
                  mono
                  required={prefixRequired}
                  description={t`Leave empty to keep the prefix of the file.`}
                />
                <Button
                  isDisabled={importType.isPending || newKey.trim() === ""}
                  onPress={() => void send({ mode: "as_new_key", new_key: newKey.trim(), ...prefixOption() })}
                  className={PRIMARY_BUTTON}
                >
                  {t`Import with the new key`}
                </Button>
              </div>
            ) : null}
            {alert}
            <Button onPress={() => { setPhase("input"); setProblem(null); setNewKeyChoice(false); }} className={`${SECONDARY_BUTTON} self-start`}>
              {t`Back`}
            </Button>
          </>
        ) : (
          <>
            <p className="text-ink-2">{t`Choose a file exported from this or another hub, or paste its contents. Files up to 64 KB.`}</p>
            <TextAreaField label={t`Export file contents`} value={text} onChange={setText} rows={6} mono />
            <label className="flex flex-col gap-1.5 text-small font-bold text-ink">
              {t`Or choose an export file`}
              <input
                type="file"
                accept=".json,application/json"
                onChange={(event) => void chooseFile(event.target.files?.[0])}
                className="min-h-11 text-ink file:mr-3 file:h-11 file:rounded-r2 file:border file:border-line-strong file:bg-surface file:px-4 file:font-bold file:text-ink"
              />
            </label>
            {prefixRequired ? (
              <TextInput label={t`New code prefix`} value={newPrefix} onChange={(v) => setNewPrefix(v.toUpperCase())} mono required />
            ) : null}
            {alert}
            <div className="flex flex-wrap gap-3">
              <Button isDisabled={importType.isPending} onPress={() => void send(prefixRequired ? prefixOption() : {})} className={PRIMARY_BUTTON}>
                {t`Import`}
              </Button>
              <Button onPress={close} className={SECONDARY_BUTTON}>{t`Cancel`}</Button>
            </div>
          </>
        )}
      </div>
    </ModalDialog>
  );
}
