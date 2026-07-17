<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ArrowDownIcon from '@lucide/svelte/icons/arrow-down-1-0';
	import ArrowUpIcon from '@lucide/svelte/icons/arrow-up-1-0';
	import { Button } from '$lib/components/ui/button';
	import * as Popover from '$lib/components/ui/popover';
	import * as Command from '$lib/components/ui/command';
	import { cn } from '$lib/utils';
	import { tick } from 'svelte';

	interface Props {
		/** Available page-size options. */
		limits: number[];
		/** Selected page size (two-way bound). */
		limit: number;
		/** Whether a sort order exists. */
		hasOrder: boolean;
		/** Ascending sort order (two-way bound). */
		orderAsc?: boolean;
		/** Current page index (0-based). */
		page: number;
		/** Whether a previous page exists. */
		hasPrev: boolean;
		/** Whether a next page exists. */
		hasNext: boolean;
		/** Navigate to the previous page. */
		onPrev: () => void;
		/** Navigate to the next page. */
		onNext: () => void;
		/** Called when limit or sort order changes; parent should reset to page 1. */
		onReset: () => void;
	}

	let {
		limits,
		limit = $bindable(),
        hasOrder = false,
		orderAsc = $bindable(),
		page,
		hasPrev,
		hasNext,
		onPrev,
		onNext,
		onReset
	}: Props = $props();

	let limit_open = $state(false);
	let triggerRef = $state<HTMLButtonElement>(null!);

	function selectLimit(value: number) {
		limit = value;
		limit_open = false;
		onReset();
		tick().then(() => {
			triggerRef.focus();
		});
	}

	function toggleSortOrder() {
		orderAsc = !orderAsc;
		onReset();
	}
</script>

<div class="flex justify-between items-center gap-10 mx-auto">
	<div class="flex justify-between items-center gap-3">
		{#if hasOrder}
			<Button onclick={toggleSortOrder} variant="outline" size="icon">
				{#if orderAsc}
					<ArrowUpIcon class="h-[1.2rem] w-[1.2rem] !transition-all " />
				{:else}
					<ArrowDownIcon class="absolute h-[1.2rem] w-[1.2rem] !transition-all " />
				{/if}
				<span class="sr-only">Toggle sort order</span>
			</Button>
		{/if}
		<Popover.Root bind:open={limit_open}>
			<Popover.Trigger bind:ref={triggerRef}>
				{#snippet child({ props })}
					<Button
						{...props}
						variant="outline"
						class="justify-between"
						role="combobox"
						aria-expanded={limit_open}
					>
						{limit}
						<ChevronsUpDownIcon class="opacity-50" />
					</Button>
				{/snippet}
			</Popover.Trigger>
			<Popover.Content class="w-[100px] p-0">
				<Command.Root>
					<Command.List>
						<Command.Empty>No limit set.</Command.Empty>
						<Command.Group value="limits">
							{#each limits as value}
								<Command.Item value={value.toString()} onSelect={() => selectLimit(value)}>
									<CheckIcon class={cn(limit !== value && 'text-transparent')} />
									{value}
								</Command.Item>
							{/each}
						</Command.Group>
					</Command.List>
				</Command.Root>
			</Popover.Content>
		</Popover.Root>
		<p>Items per page</p>
	</div>
	<div class="flex items-center gap-2">
		<Button variant="outline" size="sm" disabled={!hasPrev} onclick={onPrev}>
			<ChevronLeftIcon />
			Previous
		</Button>
		<span class="min-w-8 text-center text-sm">{page + 1}</span>
		<Button variant="outline" size="sm" disabled={!hasNext} onclick={onNext}>
			Next
			<ChevronRightIcon />
		</Button>
	</div>
</div>
