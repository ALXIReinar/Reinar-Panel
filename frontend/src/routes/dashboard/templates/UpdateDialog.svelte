<script lang="ts">
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog/index.js';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { toast } from 'svelte-sonner';
	import { Template, UpdateTemplate, UpdateTemplateForm } from '$lib/api/templates';

	let { onUpdated: onUpdated, template }: { onUpdated: () => Promise<void> | void; template: Template } =
		$props();

	let open = $state(false);
	let title_in = $derived(template.title);

	async function update() {
		let form = new UpdateTemplateForm(template.id, title_in);
		let s = await UpdateTemplate(form);
		if (s) {
			toast.success(`Updated a template`);
			await onUpdated();
		} else {
			toast.error(`Failed to update a template`);
		}
		open = false;
	}
</script>

<Dialog.Root bind:open>
	<form>
		<Dialog.Trigger>
			<Button variant="secondary" size="icon-lg">
				<PencilIcon />
			</Button>
		</Dialog.Trigger>
		<Dialog.Content>
			<Dialog.Header>
				<Dialog.Title>Update template</Dialog.Title>
			</Dialog.Header>
			<div class="grid gap-4">
				<div class="grid gap-3">
					<Label for="title-in">Title</Label>
					<Input bind:value={title_in} id="title-in" name="title"  />
				</div>
			</div>
			<Dialog.Footer>
				<Dialog.Close type="button" class={buttonVariants({ variant: 'outline' })}>
					Cancel
				</Dialog.Close>
				<Button type="button" onclick={update}>Save</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</form>
</Dialog.Root>
