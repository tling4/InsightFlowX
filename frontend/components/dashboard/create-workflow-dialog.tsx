"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Spinner } from "@/components/ui/spinner";
import { useCreateWorkflow } from "@/lib/use-workflow";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CreateWorkflowDialog({ open, onClose }: Props) {
  const [title, setTitle] = useState("");
  const router = useRouter();
  const mutation = useCreateWorkflow();

  const handleCreate = async () => {
    if (!title.trim()) return;
    const result = await mutation.mutateAsync({ title: title.trim() });
    onClose();
    setTitle("");
    router.push(`/workflows/${result.workflow_id}`);
  };

  return (
    <Modal open={open} onClose={onClose} title="新建竞品分析">
      <div className="space-y-4">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="输入分析标题，如：Notion 竞品分析"
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" onClick={handleCreate} disabled={mutation.isPending || !title.trim()}>
            {mutation.isPending ? <Spinner size={14} /> : null}
            创建
          </Button>
        </div>
      </div>
    </Modal>
  );
}
