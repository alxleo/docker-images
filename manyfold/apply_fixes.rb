# Remove each source change once the corresponding native behavior ships upstream.
def replace(path, before, after)
  source = File.read(path)
  raise "upstream source changed: #{path}" unless source.scan(before).length == 1
  File.write(path, source.sub(before, after))
end

# Merge keeps model files and already requires ModelPolicy#update? in the native controller.
replace("app/lib/client_credentials_strategy.rb",
  'when "create", "update", "raw_put"',
  'when "create", "update", "raw_put", "merge"')

replace("app/deserializers/manyfold_api/v0/model_deserializer.rb",
  'collections: @object.dig("isPartOf")&.map { CollectionDeserializer.new(object: it).deserialize },',
  'collections: @object.dig("isPartOf")&.map { dereference(it.fetch("@id"), CollectionPolicy::UpdateScope.new(@user, Collection).resolve) },')

# Dropping only the row leaves an orphan that the next scan imports again.
replace("app/models/model.rb",
  'file.delete # Don\'t run callbacks, just remove the database record',
  <<~'CODE'.chomp)
if file.attachment.storage_key == existing_file.attachment.storage_key && file.attachment.id == existing_file.attachment.id
        file.delete
      else
        file.delete_from_disk_and_destroy
      end
CODE
replace("app/models/model.rb", 'file.digest.first(6)', 'file.public_id')
replace("app/models/model.rb", "    file.update(\n      filename: new_filename,", "    file.update!(\n      filename: new_filename,")

# Puma's open request tempfile can be unlinked; Shrine must copy its readable stream.
replace("config/initializers/shrine.rb", 'upload_options = {cache: {move: true}}', 'upload_options = {cache: {move: false}}')
replace("config/initializers/shrine.rb", 'upload_options[l.storage_key] = {move: true}', 'upload_options[l.storage_key] = {move: false}')

replace("app/uploaders/model_file_uploader.rb", "  def generate_location", <<~'CODE'.chomp)
  add_metadata do |_io, context|
    record = context[:record]
    next {} unless record&.filename.present? && !context[:derivative]

    type = Mime::Type.lookup_by_extension(File.extname(record.filename).delete(".").downcase)
    {"filename" => record.basename(include_extension: true), "mime_type" => type&.to_s}.compact
  end

  def generate_location
CODE
